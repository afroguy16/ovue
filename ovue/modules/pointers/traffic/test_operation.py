"""Check that pointer traffic history is emitted as safe one-line JSON."""

import json
from pathlib import Path

import pytest

from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.traffic.operation import read_traffic
from ovue.modules.pointers.validation.validation import Payload, Policy


def test_traffic_history_contains_the_pointer_and_sender_fields(
    tmp_path: Path,
) -> None:
    """Expose the recorded pointer fields without interpreting their contents."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    send(
        Payload(
            ("seat_b",),
            "https://work.example.org/items/42",
            "CT-2",
            'Ready "for review"',
            "done",
        ),
        sender=Sender("seat_a", "Ese", "Writer"),
        known_seat_ids={"seat_a", "seat_b"},
        policy=Policy(frozenset({"work.example.org"}), 10, 1_000_000, 10),
        storage=storage,
    )

    lines = read_traffic(storage)
    record = json.loads(lines[0])

    assert len(lines) == 1
    assert record["from"] == {"id": "seat_a", "display_name": "Ese", "role": "Writer"}
    assert record["to"] == "seat_b"
    assert record["ref"] == {
        "url": "https://work.example.org/items/42",
        "title": "CT-2",
    }
    assert '\\"' in lines[0]
    storage.close()


@pytest.mark.parametrize("limit", [0, 1001])
def test_traffic_history_rejects_unbounded_page_sizes(
    limit: int,
    tmp_path: Path,
) -> None:
    """Keep operator traffic output within the configured maximum page size."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )

    with pytest.raises(ValueError, match="between 1 and 1000"):
        read_traffic(storage, limit=limit)

    storage.close()
