"""Message request types and validation owned by the message service."""

# Import dataclasses for small immutable values used inside the service.
from dataclasses import dataclass
# Import URL parsing so references can be checked without being fetched.
from urllib.parse import urlsplit


# Keep message kinds fixed so callers cannot invent protocol states.
MESSAGE_KINDS = {"done", "blocked", "needs-decision", "info", "acknowledged"}
# Keep the recipient fan-out bounded by the contract.
MAX_RECIPIENTS = 10
# Keep reference URLs small enough for logs and event payloads.
MAX_URL_LENGTH = 2_048
# Keep reference labels short and safe to render.
MAX_TITLE_LENGTH = 12
# Keep notification descriptions short and single-line.
MAX_DESCRIPTION_LENGTH = 120
# Define the exact printable ASCII characters allowed in titles.
TITLE_CHARACTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_.#")


@dataclass(frozen=True, slots=True)
class Reference:
    """A URL and optional short label pointing to externally owned work."""

    # Keep the URL as untrusted pointer data; the service never fetches it.
    url: str
    # Keep the optional title as an opaque display label.
    title: str | None = None


@dataclass(frozen=True, slots=True)
class MessageInput:
    """Validated client-supplied values for one message."""

    # Store unique recipient IDs in the original request order.
    recipients: tuple[str, ...]
    # Store the reference as a cohesive value owned by the message service.
    reference: Reference
    # Store the bounded one-line notification.
    description: str
    # Store one of the protocol's fixed message kinds.
    kind: str


def parse_message(payload: object) -> tuple[MessageInput | None, list[dict[str, object]]]:
    """Parse request JSON and collect safe shape and value issues."""

    # Start with no issues so the caller receives every detected problem.
    issues: list[dict[str, object]] = []
    # Reject a non-object body before looking up fields.
    if not isinstance(payload, dict):
        return None, [_issue([], "invalid_type", "Request body must be an object")]
    # Read each field as untrusted JSON data.
    recipients = payload.get("to")
    reference_value = payload.get("ref")
    description = payload.get("description")
    kind = payload.get("kind")
    # Require recipient IDs to be an array of strings.
    if not isinstance(recipients, list) or not all(isinstance(item, str) for item in recipients):
        issues.append(_issue(["to"], "invalid_type", "to must be an array of seat IDs"))
    # Require ref to be an object with URL fields.
    if not isinstance(reference_value, dict):
        issues.append(_issue(["ref"], "invalid_type", "ref must be an object"))
    # Require a textual description.
    if not isinstance(description, str):
        issues.append(_issue(["description"], "invalid_type", "description must be a string"))
    # Require a textual kind.
    if not isinstance(kind, str):
        issues.append(_issue(["kind"], "invalid_type", "kind must be a string"))
    # Stop if the field shapes are not sufficient to construct a message.
    if issues:
        return None, issues
    # Read URL and title only after confirming ref is an object.
    url = reference_value.get("url")
    title = reference_value.get("title")
    # Require ref.url to be a string.
    if not isinstance(url, str):
        issues.append(_issue(["ref", "url"], "required", "ref.url must be a string"))
    # Require a supplied ref.title to be a string.
    if title is not None and not isinstance(title, str):
        issues.append(_issue(["ref", "title"], "invalid_type", "ref.title must be a string"))
    # Stop if reference fields cannot form a valid value.
    if issues:
        return None, issues
    # Build the request value and collapse duplicate recipients in input order.
    message = MessageInput(
        recipients=tuple(dict.fromkeys(recipients)),
        reference=Reference(url=url, title=title),
        description=description,
        kind=kind,
    )
    # Return the parsed value for semantic validation.
    return message, issues


def validate_message(
    message: MessageInput,
    *,
    sender_id: str,
    known_seats: set[str],
    allowed_hosts: set[str],
) -> list[dict[str, object]]:
    """Validate message meaning without echoing submitted values."""

    # Accumulate issues so clients can correct several fields at once.
    issues: list[dict[str, object]] = []
    # Require at least one recipient.
    if not message.recipients:
        issues.append(_issue(["to"], "required", "At least one recipient is required"))
    # Enforce the recipient count after duplicate IDs have been collapsed.
    if len(message.recipients) > MAX_RECIPIENTS:
        issues.append(_issue(["to"], "too_many_items", "Too many recipients", max=MAX_RECIPIENTS))
    # Reject sender-to-self delivery.
    if sender_id in message.recipients:
        issues.append(_issue(["to"], "self_recipient", "A seat cannot send to itself"))
    # Reject unknown recipient IDs while allowing the reserved operator identity.
    if any(item not in known_seats and item != "operator" for item in message.recipients):
        issues.append(_issue(["to"], "unknown_seat", "Unknown seat ID"))
    # Accept only the protocol's fixed message kinds.
    if message.kind not in MESSAGE_KINDS:
        issues.append(_issue(["kind"], "invalid_enum", "Unsupported message kind"))
    # Require a non-empty description.
    if not message.description:
        issues.append(_issue(["description"], "required", "Description is required"))
    # Enforce the maximum description length.
    elif len(message.description) > MAX_DESCRIPTION_LENGTH:
        issues.append(_issue(["description"], "too_long", "Description is too long", max=MAX_DESCRIPTION_LENGTH))
    # Permit printable ASCII only to exclude control and directionality characters.
    elif any(character < " " or character > "~" for character in message.description):
        issues.append(_issue(["description"], "invalid_character", "Description must be printable ASCII"))
    # Validate title only when the optional value is present.
    if message.reference.title is not None:
        # Enforce the maximum title length.
        if len(message.reference.title) > MAX_TITLE_LENGTH:
            issues.append(_issue(["ref", "title"], "too_long", "Reference title is too long", max=MAX_TITLE_LENGTH))
        # Enforce the title's exact ASCII alphabet.
        if any(character not in TITLE_CHARACTERS for character in message.reference.title):
            issues.append(_issue(["ref", "title"], "invalid_character", "Reference title contains a disallowed character"))
    # Include every URL issue in the combined result.
    issues.extend(_validate_url(message.reference.url, allowed_hosts))
    # Return all semantic issues for the transport to serialize.
    return issues


def _validate_url(url: str, allowed_hosts: set[str]) -> list[dict[str, object]]:
    """Validate the restricted URL form accepted for a reference."""

    # Collect URL-specific issues without including the URL value.
    issues: list[dict[str, object]] = []
    # Enforce the maximum URL length.
    if len(url) > MAX_URL_LENGTH:
        issues.append(_issue(["ref", "url"], "too_long", "Reference URL is too long", max=MAX_URL_LENGTH))
    # Parse with strict IPv6 bracket and port handling from the standard library.
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return [_issue(["ref", "url"], "invalid_url", "Reference URL is invalid")]
    # Require an absolute URL with an allowed scheme and hostname.
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        issues.append(_issue(["ref", "url"], "not_absolute", "Reference URL must be absolute HTTPS"))
        return issues
    # Reject embedded credentials.
    if parsed.username is not None or parsed.password is not None:
        issues.append(_issue(["ref", "url"], "userinfo_forbidden", "URL userinfo is not allowed"))
    # Reject query strings because they may contain secrets.
    if parsed.query:
        issues.append(_issue(["ref", "url"], "query_forbidden", "URL query strings are not allowed"))
    # Reject fragments because they are unneeded opaque data.
    if parsed.fragment:
        issues.append(_issue(["ref", "url"], "fragment_forbidden", "URL fragments are not allowed"))
    # Normalize the hostname for exact allowlist comparison.
    hostname = parsed.hostname.lower()
    # Permit HTTP only for exact localhost references.
    if parsed.scheme == "http" and hostname != "localhost":
        issues.append(_issue(["ref", "url"], "invalid_scheme", "HTTP is allowed only for localhost"))
    # Reject non-default explicit ports.
    if port is not None and port != (80 if parsed.scheme == "http" else 443):
        issues.append(_issue(["ref", "url"], "invalid_port", "Only the default port is allowed"))
    # Reject IP literals, trailing-dot hosts, and IDN/punycode names.
    if any(character in hostname for character in ":[]") or hostname.endswith(".") or hostname.startswith("xn--"):
        issues.append(_issue(["ref", "url"], "invalid_host", "Host form is not allowed"))
    # Require exact allowlist membership for every non-local host.
    if hostname != "localhost" and (not allowed_hosts or hostname not in allowed_hosts):
        issues.append(_issue(["ref", "url"], "host_not_allowed", "Host is not allowed"))
    # Return all URL-specific issues.
    return issues


def _issue(
    path: list[str],
    code: str,
    message: str,
    **metadata: object,
) -> dict[str, object]:
    """Create a safe issue object containing no submitted values."""

    # Construct only the contract's path, code, and safe message fields.
    result: dict[str, object] = {"path": path, "code": code, "message": message}
    # Add configured limit metadata such as max when relevant.
    result.update(metadata)
    # Return the complete safe issue.
    return result
