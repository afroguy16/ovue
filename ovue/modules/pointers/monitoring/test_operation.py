"""Check the operator warning boundary for configured storage limits."""

from pathlib import Path

import pytest

from ovue.modules.pointers.monitoring.operation import warn_if_near_capacity
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import Payload, Policy


def test_storage_warning_is_emitted_at_eighty_percent_of_record_limit(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn the operator when the pointer count reaches its configured threshold."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    send(
        Payload(("seat_b",), "https://work.example.org/i/1", None, "Ready", "done"),
        sender=Sender("seat_a", "Ari", "Writer"),
        known_seat_ids={"seat_a", "seat_b"},
        policy=Policy(frozenset({"work.example.org"}), 5, 10_000_000, 10),
        storage=storage,
    )

    warnings = warn_if_near_capacity(
        storage,
        max_pointer_records=1,
        max_logical_database_bytes=10_000_000,
    )

    assert warnings == ("Pointer records are at least 80% of configured capacity",)
    assert "80%" in caplog.text
    storage.close()
