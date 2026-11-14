"""Validate pointer submissions against the Ovue contract and send policy."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass

from ovue.modules.pointers.utils.functions import (
    is_printable_ascii,
    split_url,
    unique_in_order,
)


@dataclass(frozen=True)
class Payload:
    """Hold the recipient IDs and external reference being submitted."""

    to: tuple[str, ...]
    ref_url: str
    ref_title: str | None
    description: str
    kind: str


@dataclass(frozen=True)
class Policy:
    """Hold the host allowlist and capacity limits for a send operation."""

    allowed_hosts: frozenset[str]
    max_pointer_records: int
    max_logical_database_bytes: int
    max_unread_per_seat: int
    local_deployment: bool = False
    max_unread_global: int = 1000


@dataclass(frozen=True)
class Issue:
    """Describe a safe validation or capacity problem."""

    code: str
    message: str
    path: tuple[str | int, ...]
    max_value: int | None = None


class IssueRejected(Exception):
    """Signal that a pointer submission must be rejected with one or more issues."""

    def __init__(self, issues: tuple[Issue, ...]) -> None:
        """Keep structured issues while leaving exception text value-free."""
        self.issues = issues
        super().__init__("Pointer operation rejected")


_KINDS = frozenset({"done", "blocked", "needs-decision", "info", "acknowledged"})
_TITLE_PATTERN = re.compile(r"[A-Za-z0-9 _.#-]*\Z")


def validate(
    payload: Payload,
    *,
    sender_id: str,
    known_seat_ids: set[str],
    policy: Policy,
) -> tuple[str, ...]:
    """Validate all pointer fields and return unique recipients in request order."""
    issues: list[Issue] = []
    recipients = unique_in_order(payload.to)

    if not payload.to:
        issues.append(Issue("required", "At least one recipient is required", ("to",)))
    if len(payload.to) > 10:
        issues.append(
            Issue(
                "too_many_recipients",
                "At most 10 recipients are allowed",
                ("to",),
                10,
            )
        )
    for recipient_id in recipients:
        if recipient_id == sender_id:
            issues.append(
                Issue("sender_is_recipient", "A seat cannot send to itself", ("to",))
            )
        elif recipient_id != "operator" and recipient_id not in known_seat_ids:
            issues.append(
                Issue("unknown_seat_id", "Recipient seat is unknown", ("to",))
            )

    issues.extend(_reference_issues(payload.ref_url, policy))
    if payload.ref_title is not None:
        if len(payload.ref_title) > 12:
            issues.append(
                Issue(
                    "too_long",
                    "Title exceeds 12 characters",
                    ("ref", "title"),
                    12,
                )
            )
        if not _TITLE_PATTERN.fullmatch(payload.ref_title):
            issues.append(
                Issue(
                    "invalid_characters",
                    "Title contains unsupported characters",
                    ("ref", "title"),
                )
            )
    if not payload.description:
        issues.append(Issue("required", "Description is required", ("description",)))
    if len(payload.description) > 120:
        issues.append(
            Issue(
                "too_long",
                "Description exceeds 120 characters",
                ("description",),
                120,
            )
        )
    if not is_printable_ascii(payload.description):
        issues.append(
            Issue(
                "invalid_characters",
                "Description must be printable ASCII only",
                ("description",),
            )
        )
    if payload.kind not in _KINDS:
        issues.append(
            Issue("unsupported_kind", "Pointer kind is unsupported", ("kind",))
        )

    if issues:
        raise IssueRejected(tuple(issues))
    return recipients


def _reference_issues(value: str, policy: Policy) -> list[Issue]:
    """Return safe issues for a reference URL without echoing its contents."""
    issues: list[Issue] = []
    if len(value) > 2048:
        issues.append(
            Issue("too_long", "URL exceeds 2048 characters", ("ref", "url"), 2048)
        )

    if any(unicodedata.category(character).startswith("C") for character in value):
        issues.append(
            Issue("invalid_url", "URL contains unsupported characters", ("ref", "url"))
        )
    parsed = split_url(value)
    if parsed is None:
        return [*issues, Issue("invalid_url", "URL is invalid", ("ref", "url"))]
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        return [*issues, Issue("invalid_url", "URL is invalid", ("ref", "url"))]

    normalized_host = hostname.lower() if hostname is not None else ""
    local_reference_host = policy.local_deployment and normalized_host == "localhost"
    allowed_http_localhost = local_reference_host and parsed.scheme == "http"
    if parsed.scheme != "https" and not allowed_http_localhost:
        issues.append(Issue("invalid_scheme", "Must be https", ("ref", "url")))
    if not parsed.scheme or not parsed.netloc or hostname is None:
        issues.append(Issue("invalid_url", "URL must be absolute", ("ref", "url")))
        return issues

    if parsed.username is not None or parsed.password is not None:
        issues.append(
            Issue(
                "userinfo_not_allowed",
                "URL user information is not allowed",
                ("ref", "url"),
            )
        )
    if "?" in value or "#" in value:
        issues.append(
            Issue(
                "query_or_fragment_not_allowed",
                "Remove the query string or fragment from the URL",
                ("ref", "url"),
            )
        )
    if port not in (None, 80 if allowed_http_localhost else 443):
        issues.append(
            Issue("non_default_port", "URL must use the default port", ("ref", "url"))
        )

    try:
        ipaddress.ip_address(normalized_host)
    except ValueError:
        is_ip_literal = False
    else:
        is_ip_literal = True
    if is_ip_literal or normalized_host.endswith(".") or "xn--" in normalized_host:
        issues.append(Issue("invalid_host", "URL host is not allowed", ("ref", "url")))
    elif not local_reference_host and normalized_host not in policy.allowed_hosts:
        issues.append(
            Issue("host_not_allowed", "URL host is not allowed", ("ref", "url"))
        )
    return issues
