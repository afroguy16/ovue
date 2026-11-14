"""Check pointer retention, traffic-log retention, and reusable database pages."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ovue.modules.pointers.purge.operation import purge
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import Payload, Policy


def test_purge_removes_only_old_fully_read_pointers_and_old_log_rows(
    tmp_path: Path,
) -> None:
    """Keep unread pointers while removing eligible pointer and log records."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    result = send(
        Payload(("seat_b",), "https://work.example.org/i/1", None, "Ready", "done"),
        sender=Sender("seat_a", "Ari", "Writer"),
        known_seat_ids={"seat_a", "seat_b"},
        policy=Policy(frozenset({"work.example.org"}), 10, 1_000_000, 10),
        storage=storage,
    )
    storage._connection.execute(
        "UPDATE pointers SET created_at = ?",
        ((datetime.now(UTC) - timedelta(days=100)).isoformat(),),
    )
    storage._connection.execute(
        "UPDATE traffic_log SET created_at = ?",
        ((datetime.now(UTC) - timedelta(days=100)).isoformat(),),
    )

    first = purge(storage, pointer_age_days=30, log_age_days=90)
    assert first.pointers_deleted == 0
    assert first.traffic_rows_deleted == 1
    assert storage.snapshot()[0] == 1

    storage._connection.execute(
        "UPDATE deliveries SET state = 'read' WHERE delivery_id = ?",
        (result.deliveries[0].delivery_id,),
    )
    second = purge(storage, pointer_age_days=30, log_age_days=90)
    assert second.pointers_deleted == 1
    assert storage.snapshot()[0] == 0
    storage.close()
