"""Check that sending pointers validates them and saves them in SQLite."""

from pathlib import Path

import pytest

from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import IssueRejected, Payload, Policy


# Use small limits so each test can quickly reach the conditions it checks.
def make_policy(*, max_pointer_records: int = 10) -> Policy:
    """Set the allowed host and small storage and inbox limits for these tests."""
    return Policy(
        allowed_hosts=frozenset({"work.example.org"}),
        max_pointer_records=max_pointer_records,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
    )


# Start with valid pointer details and let each test choose the recipient seats.
def make_payload(to: tuple[str, ...] = ("seat_b",)) -> Payload:
    """Make valid pointer details addressed to the selected recipient seats."""
    return Payload(
        to=to,
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )


# Check that each recipient seat gets one delivery, even if listed twice.
def test_send_creates_one_pointer_and_one_delivery_per_unique_recipient(
    tmp_path: Path,
) -> None:
    """Save one pointer and one delivery for each different recipient seat."""
    storage = SQLite(tmp_path / "pointers.sqlite3")

    result = send(
        make_payload(("seat_b", "seat_c", "seat_b")),
        sender=Sender(id="seat_a", display_name="Ari", role="Writer"),
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
        policy=make_policy(),
        storage=storage,
    )

    assert result.pointer_id
    assert {item.recipient_id for item in result.deliveries} == {"seat_b", "seat_c"}
    assert all(item.state == "unread" for item in result.deliveries)
    storage.close()


# Check that one full inbox prevents the entire send from being saved.
def test_send_rejects_full_inbox_without_creating_partial_deliveries(
    tmp_path: Path,
) -> None:
    """Save nothing when one recipient's inbox is full, even if another has room."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    sender = Sender(id="seat_a", display_name="Ari", role="Writer")
    known_seat_ids = {"seat_a", "seat_b", "seat_c"}
    policy = make_policy()

    for _ in range(2):
        send(
            make_payload(("seat_b",)),
            sender=sender,
            known_seat_ids=known_seat_ids,
            policy=policy,
            storage=storage,
        )
    before = storage.snapshot()

    with pytest.raises(IssueRejected) as error:
        send(
            make_payload(("seat_c", "seat_b")),
            sender=sender,
            known_seat_ids=known_seat_ids,
            policy=policy,
            storage=storage,
        )

    assert any(issue.code == "recipient_inbox_full" for issue in error.value.issues)
    assert storage.snapshot() == before
    storage.close()


# Check that sending stops when the database already has its maximum pointers.
def test_send_rejects_storage_limit_without_writing_rows(tmp_path: Path) -> None:
    """Save no more pointers after the database reaches its pointer limit."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    sender = Sender(id="seat_a", display_name="Ari", role="Writer")
    known_seat_ids = {"seat_a", "seat_b"}
    policy = make_policy(max_pointer_records=2)

    for _ in range(2):
        send(
            make_payload(),
            sender=sender,
            known_seat_ids=known_seat_ids,
            policy=policy,
            storage=storage,
        )
    before = storage.snapshot()

    with pytest.raises(IssueRejected) as error:
        send(
            make_payload(),
            sender=sender,
            known_seat_ids=known_seat_ids,
            policy=policy,
            storage=storage,
        )

    assert any(issue.code == "storage_limit_reached" for issue in error.value.issues)
    assert storage.snapshot() == before
    storage.close()
