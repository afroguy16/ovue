"""Check that one seat can acknowledge only its own pointer delivery."""

from pathlib import Path

import pytest

from ovue.modules.pointers.acknowledgement.operation import acknowledge
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import Payload, Policy


def test_acknowledgement_is_idempotent_and_changes_only_one_recipient(
    tmp_path: Path,
) -> None:
    """Make repeated acknowledgements harmless and preserve other recipients' state."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    payload = Payload(
        ("seat_b", "seat_c"),
        "https://work.example.org/items/42",
        None,
        "Ready",
        "done",
    )
    result = send(
        payload,
        sender=Sender("seat_a", "Ari", "Writer"),
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
        policy=Policy(frozenset({"work.example.org"}), 10, 1_000_000, 10),
        storage=storage,
    )

    acknowledge(storage, result.deliveries[0].delivery_id, recipient_id="seat_b")
    acknowledge(storage, result.deliveries[0].delivery_id, recipient_id="seat_b")

    items_b = storage.get_inbox("seat_b", unread=None, after_sequence=0, limit=50)
    items_c = storage.get_inbox("seat_c", unread=None, after_sequence=0, limit=50)
    assert items_b[0]["state"] == "read"
    assert items_c[0]["state"] == "unread"
    storage.close()


def test_acknowledgement_hides_unknown_and_foreign_delivery_ids(
    tmp_path: Path,
) -> None:
    """Return the same not-found result for unknown and another seat's delivery."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    result = send(
        Payload(("seat_b",), "https://work.example.org/i/1", None, "Ready", "done"),
        sender=Sender("seat_a", "Ari", "Writer"),
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
        policy=Policy(frozenset({"work.example.org"}), 10, 1_000_000, 10),
        storage=storage,
    )

    with pytest.raises(LookupError, match="Delivery not found"):
        acknowledge(storage, result.deliveries[0].delivery_id, recipient_id="seat_c")
    with pytest.raises(LookupError, match="Delivery not found"):
        acknowledge(storage, "unknown-delivery", recipient_id="seat_c")
    storage.close()
