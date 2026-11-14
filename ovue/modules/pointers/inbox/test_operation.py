"""Check inbox filtering, ordering, and cursor-based pagination."""

from pathlib import Path

import pytest

from ovue.modules.pointers.acknowledgement.operation import acknowledge
from ovue.modules.pointers.inbox.operation import get_inbox
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import Payload, Policy


def make_policy() -> Policy:
    """Set permissive test capacity while allowing the example reference host."""
    return Policy(frozenset({"work.example.org"}), 100, 10_000_000, 100)


def make_payload() -> Payload:
    """Make a valid pointer addressed to the inbox recipient."""
    return Payload(
        ("seat_b",),
        "https://work.example.org/items/42",
        "CT-2",
        "Ready for review",
        "done",
    )


def test_inbox_returns_unread_and_read_deliveries_with_opaque_paging(
    tmp_path: Path,
) -> None:
    """Return deliveries in sequence order and provide a cursor for the next page."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    sender = Sender("seat_a", "Ari", "Writer")
    for _ in range(3):
        send(
            make_payload(),
            sender=sender,
            known_seat_ids={"seat_a", "seat_b"},
            policy=make_policy(),
            storage=storage,
        )

    first = get_inbox(storage, "seat_b", limit=2)
    second = get_inbox(storage, "seat_b", limit=2, cursor=first.next_cursor)

    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert len(second.items) == 1
    assert second.next_cursor is None
    assert [item["event_id"] for item in first.items + second.items] == [1, 2, 3]
    storage.close()


def test_inbox_filter_selects_unread_or_acknowledged_deliveries(
    tmp_path: Path,
) -> None:
    """Return only the requested state while leaving default inbox behavior intact."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    sender = Sender("seat_a", "Ari", "Writer")
    result = send(
        make_payload(),
        sender=sender,
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
        storage=storage,
    )
    acknowledge(storage, result.deliveries[0].delivery_id, recipient_id="seat_b")
    send(
        make_payload(),
        sender=sender,
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
        storage=storage,
    )

    assert [
        item["state"] for item in get_inbox(storage, "seat_b", unread=True).items
    ] == ["unread"]
    assert [
        item["state"] for item in get_inbox(storage, "seat_b", unread=False).items
    ] == ["read"]
    assert len(get_inbox(storage, "seat_b").items) == 2
    storage.close()


@pytest.mark.parametrize("limit", [0, 101])
def test_inbox_rejects_limits_outside_the_contract(limit: int, tmp_path: Path) -> None:
    """Reject a page size below one or above the maximum of one hundred."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    with pytest.raises(ValueError):
        get_inbox(storage, "seat_b", limit=limit)
    storage.close()
