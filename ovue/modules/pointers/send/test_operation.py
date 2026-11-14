"""Check that sending pointers validates them and saves them in SQLite."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from ovue.modules.pointers.acknowledgement.operation import acknowledge
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.pointers.validation.validation import (
    IssueRejected,
    Payload,
    Policy,
)
from ovue.modules.seats.storage.sqlite import SeatStorage


def make_policy(
    *,
    max_pointer_records: int = 10,
    max_unread_per_seat: int = 2,
    max_unread_global: int = 1000,
    max_logical_database_bytes: int = 1_000_000,
) -> Policy:
    """Set the allowed host and small storage and inbox limits for these tests."""
    return Policy(
        allowed_hosts=frozenset({"work.example.org"}),
        max_pointer_records=max_pointer_records,
        max_logical_database_bytes=max_logical_database_bytes,
        max_unread_per_seat=max_unread_per_seat,
        max_unread_global=max_unread_global,
    )


def make_payload(to: tuple[str, ...] = ("seat_b",)) -> Payload:
    """Make valid pointer details addressed to the selected recipient seats."""
    return Payload(
        to=to,
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )


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


def test_send_rolls_back_if_resulting_sqlite_pages_exceed_logical_limit(
    tmp_path: Path,
) -> None:
    """Keep the logical-size cap even when an accepted write needs new pages."""
    storage = SQLite(tmp_path / "pointers.sqlite3")
    sender = Sender(id="seat_a", display_name="Ari", role="Writer")
    policy = make_policy(max_logical_database_bytes=65_000)
    recipients = tuple(f"seat_{index}" for index in range(10))
    url_prefix = "https://work.example.org/"
    payload = Payload(
        to=recipients,
        ref_url=url_prefix + "a" * (2048 - len(url_prefix)),
        ref_title="CT-2",
        description="x" * 120,
        kind="done",
    )

    with pytest.raises(IssueRejected) as error:
        send(
            payload,
            sender=sender,
            known_seat_ids={"seat_a", *recipients},
            policy=policy,
            storage=storage,
        )

    assert error.value.issues[0].code == "storage_limit_reached"
    assert storage.snapshot() == (0, 0, 0)
    assert storage.capacity_usage().logical_database_bytes <= 65_000
    storage.close()


def test_concurrent_sends_do_not_exceed_the_pointer_record_limit(
    tmp_path: Path,
) -> None:
    """Serialize concurrent capacity checks so only one send uses the last slot."""
    database_path = tmp_path / "pointers.sqlite3"
    first_storage = SQLite(database_path)
    second_storage = SQLite(database_path)
    sender = Sender(id="seat_a", display_name="Ari", role="Writer")
    policy = make_policy(max_pointer_records=1)
    barrier = Barrier(2)

    def submit(storage: SQLite) -> str:
        """Race one valid send against the other connection's final storage slot."""
        barrier.wait()
        try:
            send(
                make_payload(),
                sender=sender,
                known_seat_ids={"seat_a", "seat_b"},
                policy=policy,
                storage=storage,
            )
        except IssueRejected:
            return "rejected"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(submit, (first_storage, second_storage)))

    assert sorted(outcomes) == ["rejected", "saved"]
    assert first_storage.snapshot() == (1, 1, 1)
    first_storage.close()
    second_storage.close()


def test_global_unread_limit_preserves_each_registered_seats_reservation(
    tmp_path: Path,
) -> None:
    """Keep ten unread slots available to every other registered seat."""
    database_path = tmp_path / "pointers.sqlite3"
    seats = SeatStorage(database_path)
    first, _ = seats.create_seat("writer", "Ese", "Writer")
    second, _ = seats.create_seat("reviewer", "Ari", "Reviewer")
    storage = SQLite(database_path)
    policy = make_policy(
        max_pointer_records=100,
        max_unread_per_seat=100,
        max_unread_global=20,
    )
    sender = Sender(id=first.id, display_name=first.display_name, role=first.role)

    for _ in range(10):
        send(
            make_payload((second.id,)),
            sender=sender,
            known_seat_ids={first.id, second.id},
            policy=policy,
            storage=storage,
        )
    sender = Sender(id=second.id, display_name=second.display_name, role=second.role)
    for _ in range(10):
        send(
            make_payload((first.id,)),
            sender=sender,
            known_seat_ids={first.id, second.id},
            policy=policy,
            storage=storage,
        )

    with pytest.raises(IssueRejected) as error:
        send(
            make_payload((first.id,)),
            sender=sender,
            known_seat_ids={first.id, second.id},
            policy=policy,
            storage=storage,
        )
    assert error.value.issues[0].code == "global_inbox_full"

    seats.close()
    storage.close()


def test_acknowledgement_token_revoke_and_purge_work_at_storage_limit(
    tmp_path: Path,
) -> None:
    """Keep recovery operations available when pointer sends reach the logical cap."""
    database_path = tmp_path / "pointers.sqlite3"
    seats = SeatStorage(database_path)
    sender_seat, _ = seats.create_seat("writer", "Ese", "Writer")
    recipient_seat, _ = seats.create_seat("reviewer", "Ari", "Reviewer")
    storage = SQLite(database_path)
    sender = Sender(sender_seat.id, sender_seat.display_name, sender_seat.role)
    known_seat_ids = {sender_seat.id, recipient_seat.id}
    policy = make_policy(
        max_pointer_records=10_000,
        max_unread_per_seat=1000,
        max_unread_global=1000,
        max_logical_database_bytes=200_000,
    )
    pending_delivery_id: str | None = None

    for _ in range(10_000):
        try:
            result = send(
                make_payload((recipient_seat.id,)),
                sender=sender,
                known_seat_ids=known_seat_ids,
                policy=policy,
                storage=storage,
            )
        except IssueRejected as error:
            assert error.issues[0].code == "storage_limit_reached"
            break
        if pending_delivery_id is not None:
            acknowledge(storage, pending_delivery_id, recipient_id=recipient_seat.id)
        pending_delivery_id = result.deliveries[0].delivery_id
    else:
        pytest.fail("The logical storage limit was not reached")

    assert pending_delivery_id is not None
    assert storage.capacity_usage().logical_database_bytes <= 200_000
    acknowledge(storage, pending_delivery_id, recipient_id=recipient_seat.id)
    seats.revoke_token(sender_seat.id)
    storage.purge(
        pointer_age_days=1,
        log_age_days=1,
        now=datetime.now(UTC) + timedelta(days=2),
    )
    assert storage.snapshot() == (0, 0, 0)

    send(
        make_payload((recipient_seat.id,)),
        sender=sender,
        known_seat_ids=known_seat_ids,
        policy=policy,
        storage=storage,
    )

    storage.close()
    seats.close()
