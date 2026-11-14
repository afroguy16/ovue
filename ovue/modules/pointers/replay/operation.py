"""Validate per-seat event cursors and retrieve retained pointer events."""

from ovue.modules.pointers.storage.sqlite import SQLite


def replay_after(
    storage: SQLite,
    seat_id: str,
    last_event_id: str,
    *,
    limit: int = 1000,
) -> tuple[dict[str, object], ...]:
    """Return events after Last-Event-ID or raise a safe cursor error."""
    if not last_event_id.isascii() or not last_event_id.isdecimal():
        raise ValueError("Event cursor is invalid") from None
    sequence = int(last_event_id)
    if sequence < 0:
        raise ValueError("Event cursor is invalid")
    return storage.replay_after(seat_id, sequence, limit=limit)


def unread_backlog(
    storage: SQLite,
    seat_id: str,
) -> tuple[dict[str, object], ...]:
    """Return the bounded unread inbox before a new live stream begins."""
    return storage.get_inbox(seat_id, unread=True, after_sequence=0, limit=101)
