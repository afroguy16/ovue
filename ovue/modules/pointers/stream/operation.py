"""Prepare the initial stream response and fetch subsequent events."""

from dataclasses import dataclass

from ovue.modules.pointers.storage.sqlite import SQLite


@dataclass(frozen=True)
class StreamStart:
    """Hold the events to send first and the next sequence to poll from."""

    events: tuple[dict[str, object], ...]
    next_sequence: int


def start_stream(
    storage: SQLite,
    seat_id: str,
    *,
    last_event_id: str | None,
    replay_limit: int = 1000,
    unread_limit: int = 100,
) -> StreamStart:
    """Send unread backlog on a new connection or replay after its last event."""
    if last_event_id is None:
        events, latest = storage.initial_stream_state(seat_id, unread_limit)
        if len(events) > unread_limit:
            raise RuntimeError("Unread backlog exceeds the configured inbox limit")
        return StreamStart(events, latest)
    if not last_event_id.isascii() or not last_event_id.isdecimal():
        raise ValueError("Event cursor is invalid") from None
    sequence = int(last_event_id)
    if sequence < 0:
        raise ValueError("Event cursor is invalid")
    events = storage.replay_after(seat_id, sequence, limit=replay_limit)
    return StreamStart(events, sequence)


def events_after(
    storage: SQLite,
    seat_id: str,
    sequence: int,
    *,
    replay_limit: int = 1000,
) -> tuple[dict[str, object], ...]:
    """Return later deliveries for an already-open seat stream."""
    return storage.replay_after(seat_id, sequence, limit=replay_limit)
