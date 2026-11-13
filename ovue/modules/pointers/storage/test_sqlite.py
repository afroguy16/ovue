"""Check that SQLite saves pointers and keeps them after reopening the database."""

from pathlib import Path

from ovue.modules.pointers.storage.sqlite import PointerRecord, SQLite


# Check that saving a pointer also saves its recipient delivery and log entry.
def test_persist_send_stores_pointer_delivery_and_log_rows(tmp_path: Path) -> None:
    """Save the pointer, its recipient delivery, and one traffic log entry."""
    database_path = tmp_path / "pointers.sqlite3"
    storage = SQLite(database_path)
    pointer = PointerRecord(
        sender_id="seat_a",
        sender_display_name="Ari",
        sender_role="Writer",
        recipients=("seat_b",),
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )

    pointer_id, deliveries = storage.persist_send(
        pointer,
        max_pointer_records=10,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
    )

    assert pointer_id
    assert len(deliveries) == 1
    assert deliveries[0].recipient_id == "seat_b"
    assert storage.snapshot() == (1, 1, 1)
    storage.close()


# Check that saved pointers are still present after reopening the database.
def test_persisted_rows_survive_reopening_the_database(tmp_path: Path) -> None:
    """Keep saved pointer details after closing and reopening the database."""
    database_path = tmp_path / "pointers.sqlite3"
    storage = SQLite(database_path)
    pointer = PointerRecord(
        sender_id="seat_a",
        sender_display_name="Ari",
        sender_role="Writer",
        recipients=("seat_b",),
        ref_url="https://work.example.org/items/42",
        ref_title=None,
        description="Ready for review",
        kind="done",
    )
    storage.persist_send(
        pointer,
        max_pointer_records=10,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
    )
    storage.close()

    reopened = SQLite(database_path)

    assert reopened.snapshot() == (1, 1, 1)
    reopened.close()
