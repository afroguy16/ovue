"""Check ordered event replay, cursor errors, and unread backlog recovery."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ovue.modules.pointers.acknowledgement.operation import acknowledge
from ovue.modules.pointers.replay.operation import replay_after, unread_backlog
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import Payload, Policy


def save_pointer(storage: SQLite) -> str:
    """Save one test pointer and return its recipient delivery ID."""
    result = send(
        Payload(("seat_b",), "https://work.example.org/i/1", None, "Ready", "done"),
        sender=Sender("seat_a", "Ari", "Writer"),
        known_seat_ids={"seat_a", "seat_b"},
        policy=Policy(frozenset({"work.example.org"}), 10, 1_000_000, 100),
        storage=storage,
    )
    return result.deliveries[0].delivery_id


def test_replay_preserves_delivery_ids_and_recipient_sequence_order(
    tmp_path: Path,
) -> None:
    """Return later events in sequence order with stable delivery IDs."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    first_id = save_pointer(storage)
    save_pointer(storage)

    events = replay_after(storage, "seat_b", "0")

    assert [event["event_id"] for event in events] == [1, 2]
    assert events[0]["delivery_id"] == first_id
    assert replay_after(storage, "seat_b", "0")[0]["delivery_id"] == first_id
    storage.close()


@pytest.mark.parametrize("cursor", ["bad", "-1", "9"])
def test_replay_rejects_malformed_negative_or_future_cursors(
    cursor: str,
    tmp_path: Path,
) -> None:
    """Reject a cursor that cannot identify a valid point in the seat sequence."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    save_pointer(storage)
    with pytest.raises(ValueError):
        replay_after(storage, "seat_b", cursor)
    storage.close()


def test_replay_requires_inbox_recovery_when_earlier_events_were_purged(
    tmp_path: Path,
) -> None:
    """Use inbox recovery when the retained event history starts after the cursor."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    first_id = save_pointer(storage)
    save_pointer(storage)
    first_pointer_id = storage._connection.execute(
        "SELECT pointer_id FROM deliveries WHERE delivery_id = ?", (first_id,)
    ).fetchone()[0]
    storage._connection.execute(
        "DELETE FROM deliveries WHERE delivery_id = ?", (first_id,)
    )
    storage._connection.execute(
        "DELETE FROM pointers WHERE pointer_id = ?", (first_pointer_id,)
    )

    with pytest.raises(RuntimeError, match="no longer retained"):
        replay_after(storage, "seat_b", "0")
    storage.close()


def test_new_stream_backlog_contains_only_unread_deliveries(tmp_path: Path) -> None:
    """Provide unread deliveries to a new stream before it begins live polling."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    first_id = save_pointer(storage)
    save_pointer(storage)
    acknowledge(storage, first_id, recipient_id="seat_b")

    backlog = unread_backlog(storage, "seat_b")

    assert len(backlog) == 1
    assert backlog[0]["state"] == "unread"
    storage.close()


def test_event_sequence_survives_purging_all_deliveries(tmp_path: Path) -> None:
    """Keep recipient event IDs increasing after retained pointer history is purged."""
    database_path = tmp_path / "pointers.sqlite3"
    storage = SQLite(database_path)
    first_id = save_pointer(storage)
    second_id = save_pointer(storage)
    acknowledge(storage, first_id, recipient_id="seat_b")
    acknowledge(storage, second_id, recipient_id="seat_b")

    storage.purge(
        pointer_age_days=1,
        log_age_days=90,
        now=datetime.now(UTC) + timedelta(days=2),
    )
    storage.close()

    storage = SQLite(database_path)

    assert storage.latest_sequence("seat_b") == 2
    with pytest.raises(RuntimeError, match="no longer retained"):
        replay_after(storage, "seat_b", "0")

    save_pointer(storage)
    events = replay_after(storage, "seat_b", "2")

    assert [event["event_id"] for event in events] == [3]
    storage.close()
