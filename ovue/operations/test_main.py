"""Test every public pointer operation through the shared operations boundary."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.seats.storage.sqlite import SeatStorage
from ovue.operations.main import (
    Sender,
    acknowledge,
    events_after,
    get_inbox,
    purge,
    read_traffic,
    replay_after,
    send,
    start_stream,
    unread_backlog,
    warn_if_near_capacity,
)
from ovue.operations.validation import IssueRejected, Payload, Policy


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


def test_inbox_returns_unread_and_read_deliveries_with_opaque_paging(
    tmp_path: Path,
) -> None:
    """Return deliveries in sequence order and provide a cursor for the next page."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    sender = Sender("seat_a", "Ari", "Writer")
    for _ in range(3):
        send(
            make_payload(),
            sender=sender,
            known_seat_ids={"seat_a", "seat_b"},
            policy=make_policy(max_unread_per_seat=100),
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    with pytest.raises(ValueError):
        get_inbox(storage, "seat_b", limit=limit)
    storage.close()


def test_storage_warning_is_emitted_at_eighty_percent_of_record_limit(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn the operator when the pointer count reaches its configured threshold."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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


def test_purge_removes_only_old_fully_read_pointers_and_old_log_rows(
    tmp_path: Path,
) -> None:
    """Keep unread pointers while removing eligible pointer and log records."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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


def test_replay_preserves_delivery_ids_and_recipient_sequence_order(
    tmp_path: Path,
) -> None:
    """Return later events in sequence order with stable delivery IDs."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    save_pointer(storage)
    with pytest.raises(ValueError):
        replay_after(storage, "seat_b", cursor)
    storage.close()


def test_replay_requires_inbox_recovery_when_earlier_events_were_purged(
    tmp_path: Path,
) -> None:
    """Use inbox recovery when the retained event history starts after the cursor."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(database_path, max_logical_database_bytes=1_000_000)
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

    storage = SQLite(database_path, max_logical_database_bytes=1_000_000)

    assert storage.latest_sequence("seat_b") == 2
    with pytest.raises(RuntimeError, match="no longer retained"):
        replay_after(storage, "seat_b", "0")

    save_pointer(storage)
    events = replay_after(storage, "seat_b", "2")

    assert [event["event_id"] for event in events] == [3]
    storage.close()


def test_send_creates_one_pointer_and_one_delivery_per_unique_recipient(
    tmp_path: Path,
) -> None:
    """Save one pointer and one delivery for each different recipient seat."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )

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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    first_storage = SQLite(database_path, max_logical_database_bytes=1_000_000)
    second_storage = SQLite(database_path, max_logical_database_bytes=1_000_000)
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
    seats = SeatStorage(database_path, max_logical_database_bytes=1_000_000)
    first, _ = seats.create_seat("writer", "Ese", "Writer")
    second, _ = seats.create_seat("reviewer", "Ari", "Reviewer")
    storage = SQLite(database_path, max_logical_database_bytes=1_000_000)
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
    seats = SeatStorage(
        database_path,
        max_logical_database_bytes=200_000,
    )
    sender_seat, _ = seats.create_seat("writer", "Ese", "Writer")
    recipient_seat, _ = seats.create_seat("reviewer", "Ari", "Reviewer")
    storage = SQLite(
        database_path,
        max_logical_database_bytes=200_000,
    )
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
    replacement_token = seats.rotate_token(sender_seat.id)
    assert seats.authenticate(replacement_token).id == sender_seat.id
    seat_page_limit = int(
        seats._connection.execute("PRAGMA max_page_count").fetchone()[0]
    )
    pointer_page_limit = int(
        storage._connection.execute("PRAGMA max_page_count").fetchone()[0]
    )
    assert seat_page_limit == pointer_page_limit
    page_count = int(storage._connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(storage._connection.execute("PRAGMA page_size").fetchone()[0])
    assert page_count <= seat_page_limit
    assert database_path.stat().st_size <= seat_page_limit * page_size
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


def test_new_stream_receives_unread_backlog_then_starts_after_latest_sequence(
    tmp_path: Path,
) -> None:
    """Send unread items first and avoid replaying older read items as live events."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
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
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    first_id = save_pointer(storage)
    second_id = save_pointer(storage)

    start = start_stream(storage, "seat_b", last_event_id="1")

    assert [item["delivery_id"] for item in start.events] == [second_id]
    assert start.events[0]["delivery_id"] != first_id
    storage.close()


def test_new_stream_rejects_malformed_or_negative_event_id(tmp_path: Path) -> None:
    """Reject malformed and negative resume cursors before opening the stream."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3", max_logical_database_bytes=1_000_000
    )
    for cursor in ("invalid", "-1"):
        with pytest.raises(ValueError):
            start_stream(storage, "seat_b", last_event_id=cursor)
    storage.close()


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
