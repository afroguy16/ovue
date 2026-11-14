"""Check initial SSE backlog and reconnect behavior using durable deliveries."""

from pathlib import Path

import pytest

from ovue.modules.pointers.acknowledgement.operation import acknowledge
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.stream.operation import events_after, start_stream
from ovue.modules.pointers.validation.validation import Payload, Policy


def save_pointer(storage: SQLite) -> str:
    """Save one test pointer addressed to the stream recipient."""
    result = send(
        Payload(("seat_b",), "https://work.example.org/i/1", None, "Ready", "done"),
        sender=Sender("seat_a", "Ari", "Writer"),
        known_seat_ids={"seat_a", "seat_b"},
        policy=Policy(frozenset({"work.example.org"}), 10, 1_000_000, 100),
        storage=storage,
    )
    return result.deliveries[0].delivery_id


def test_new_stream_receives_unread_backlog_then_starts_after_latest_sequence(
    tmp_path: Path,
) -> None:
    """Send unread items first and avoid replaying older read items as live events."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    first_id = save_pointer(storage)
    save_pointer(storage)
    acknowledge(storage, first_id, recipient_id="seat_b")

    start = start_stream(storage, "seat_b", last_event_id=None)
    later_id = save_pointer(storage)
    later = events_after(storage, "seat_b", start.next_sequence)

    assert len(start.events) == 1
    assert start.events[0]["delivery_id"] != first_id
    assert start.next_sequence == 2
    assert [item["delivery_id"] for item in later] == [later_id]
    storage.close()


def test_reconnected_stream_replays_events_after_last_event_id(
    tmp_path: Path,
) -> None:
    """Replay later events with stable IDs when a connection resumes."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    first_id = save_pointer(storage)
    second_id = save_pointer(storage)

    start = start_stream(storage, "seat_b", last_event_id="1")

    assert [item["delivery_id"] for item in start.events] == [second_id]
    assert start.events[0]["delivery_id"] != first_id
    storage.close()


def test_new_stream_rejects_malformed_or_negative_event_id(tmp_path: Path) -> None:
    """Reject malformed and negative resume cursors before opening the stream."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    for cursor in ("invalid", "-1"):
        with pytest.raises(ValueError):
            start_stream(storage, "seat_b", last_event_id=cursor)
    storage.close()
