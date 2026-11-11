"""Application service for validating and executing Ovue actions."""

# Import the standard-library JSON module for public response values.
from typing import Any

# Import the domain models and validator.
from ovue.services.messages import MessageInput, parse_message, validate_message

# Import the persistence boundary.
from ovue.storage.sqlite import Storage


class ServiceError(Exception):
    """Represent an expected protocol failure."""

    # Store the public HTTP status for this protocol failure.
    def __init__(self, status: int, code: str, message: str) -> None:
        # Initialize the normal exception value.
        super().__init__(message)
        # Keep the HTTP status private to the transport boundary.
        self.status = status
        # Keep the stable top-level error code.
        self.code = code
        # Keep the safe human-facing error message.
        self.message = message


class MessageService:
    """Coordinate authentication, validation, and storage."""

    # Store the persistence implementation and URL policy.
    def __init__(self, storage: Storage, allowed_hosts: set[str] | None = None) -> None:
        # Keep the storage dependency behind the service boundary.
        self.storage = storage
        # Require an explicit host allowlist for non-localhost references.
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or set())}

    def authenticate(self, authorization: str | None) -> dict[str, str]:
        """Authenticate a bearer header and return public seat metadata."""

        # Reject missing authorization without revealing seat information.
        if not authorization or not authorization.startswith("Bearer "):
            raise ServiceError(401, "unauthorized", "Bearer authentication is required")
        # Extract the token after the exact bearer prefix.
        raw_token = authorization.removeprefix("Bearer ")
        # Reject an empty token before querying credentials.
        if not raw_token:
            raise ServiceError(401, "unauthorized", "Bearer authentication is required")
        # Ask storage to perform constant-time token verification.
        seat = self.storage.authenticate(raw_token)
        # Use one generic failure for all invalid credentials.
        if seat is None:
            raise ServiceError(401, "unauthorized", "Bearer authentication failed")
        # Return only identity fields that the service needs.
        return {
            "id": str(seat["id"]),
            "display_name": str(seat["display_name"]),
            "role": str(seat["role"]),
        }

    def seats(self) -> list[dict[str, object]]:
        """Return the authenticated seat directory."""

        # Convert storage rows into token-free JSON objects.
        return [
            {
                "id": str(row["id"]),
                "display_name": str(row["display_name"]),
                "role": str(row["role"]),
            }
            for row in self.storage.list_seats()
        ]

    def send(self, sender_id: str, payload: dict[str, Any]) -> list[dict[str, object]]:
        """Validate and durably send one message."""

        # Convert the external JSON object into the domain model.
        message, shape_issues = parse_message(payload)
        # Continue collecting validation issues even when the shape is incomplete.
        if message is None:
            raise _validation_error(shape_issues)
        # Validate the complete contract without echoing submitted values.
        issues = shape_issues + validate_message(
            message,
            sender_id=sender_id,
            known_seats=self.storage.known_seats(),
            allowed_hosts=self.allowed_hosts,
        )
        # Reject every issue together before storage mutation.
        if issues:
            raise _validation_error(issues)
        # Persist all recipients before returning success.
        return self.storage.send(sender_id, message)

    def inbox(self, seat_id: str, unread_only: bool) -> list[dict[str, object]]:
        """Return a seat's inbox without exposing credentials."""

        # Convert stored rows into the public event shape.
        return [_event_from_row(row) for row in self.storage.inbox(seat_id, unread_only)]

    def acknowledge(self, seat_id: str, delivery_id: str) -> None:
        """Acknowledge one delivery without allowing cross-seat probing."""

        # Update only a delivery owned by the authenticated seat.
        changed = self.storage.acknowledge(seat_id, delivery_id)
        # A second acknowledgement is harmless, but foreign IDs remain opaque.
        if not changed:
            raise ServiceError(404, "not_found", "Delivery not found")

    def stream_events(self, seat_id: str, last_sequence: int | None) -> list[dict[str, object]]:
        """Return the current stream backlog for a seat."""

        # Use unread backlog on a first connection as defined by the contract.
        if last_sequence is None:
            return self.inbox(seat_id, unread_only=True)
        # Use the recipient sequence for resumable connections.
        return [_event_from_row(row) for row in self.storage.stream_after(seat_id, last_sequence)]


def _event_from_row(row: Any) -> dict[str, object]:
    """Map one database row to a public message event."""

    # Return only fields that clients need to render and process the event.
    return {
        "event_id": int(row["sequence"]),
        "delivery_id": str(row["delivery_id"]),
        "message_id": str(row["message_id"]),
        "created_at": str(row["created_at"]),
        "from": {"id": str(row["sender_id"]), "display_name": "", "role": ""},
        "to": [str(row["recipient_id"])],
        "ref": {"url": str(row["ref_url"]), "title": row["ref_title"]},
        "description": str(row["description"]),
        "kind": str(row["kind"]),
        "state": str(row["state"]),
    }


def _validation_error(issues: list[dict[str, object]]) -> ServiceError:
    """Create a validation error carrying all safe issue details."""

    # Encode the structured issue list as a private attribute for HTTP rendering.
    error = ServiceError(400, "validation_failed", "Request validation failed")
    # Attach only safe validation metadata to the expected service exception.
    error.issues = issues  # type: ignore[attr-defined]
    # Return the fully populated protocol error.
    return error


