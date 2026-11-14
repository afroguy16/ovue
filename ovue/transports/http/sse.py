"""Format standards-compliant single-line Server-Sent Event records."""

import json


def encode_event(event: dict[str, object]) -> bytes:
    """Encode a pointer event with a per-recipient sequence and JSON data line."""
    event_id = event["event_id"]
    payload = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
    return f"id: {event_id}\ndata: {payload}\n\n".encode("ascii")


def heartbeat() -> bytes:
    """Return a comment heartbeat that does not create a client message event."""
    return b": keep-alive\n\n"
