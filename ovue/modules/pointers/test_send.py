"""Test the first send slice through its public service interface."""

from dataclasses import replace
from pathlib import Path

import pytest

from ovue.modules.pointers.service import (
    AuthenticatedSeat,
    PointerService,
    PointerSettings,
    SendCommand,
    SendValidationError,
)
from ovue.modules.pointers.storage import SQLitePointerStorage


ALLOWED_HOSTS = frozenset({"work.example.org"})


def make_service(
    tmp_path: Path, *, max_pointer_records: int = 10
) -> tuple[PointerService, SQLitePointerStorage]:
    """Build the service with isolated SQLite storage and finite test limits."""
    storage = SQLitePointerStorage(tmp_path / "pointers.sqlite3")
    settings = PointerSettings(
        allowed_hosts=ALLOWED_HOSTS,
        max_pointer_records=max_pointer_records,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
    )
    return PointerService(storage=storage, settings=settings), storage


def make_command(*, recipients: tuple[str, ...] = ("seat_b",)) -> SendCommand:
    """Return a valid pointer command that tests can vary one field at a time."""
    return SendCommand(
        to=recipients,
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )


def test_send_creates_one_pointer_and_a_delivery_per_unique_recipient(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)

    result = service.send(
        sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
        command=make_command(recipients=("seat_b", "seat_c", "seat_b")),
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
    )

    assert result.pointer_id
    assert len(result.deliveries) == 2
    assert {delivery.recipient_id for delivery in result.deliveries} == {
        "seat_b",
        "seat_c",
    }
    assert all(delivery.state == "unread" for delivery in result.deliveries)


def test_send_rejects_sender_as_recipient(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)

    with pytest.raises(SendValidationError) as error:
        service.send(
            sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
            command=make_command(recipients=("seat_a",)),
            known_seat_ids={"seat_a", "seat_b"},
        )

    assert any(issue.code == "sender_is_recipient" for issue in error.value.issues)


def test_send_rejects_unknown_recipient_without_echoing_its_id(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)
    unknown_id = "secret-seat-value"

    with pytest.raises(SendValidationError) as error:
        service.send(
            sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
            command=make_command(recipients=(unknown_id,)),
            known_seat_ids={"seat_a", "seat_b"},
        )

    assert any(issue.code == "unknown_seat_id" for issue in error.value.issues)
    assert unknown_id not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        ("ref_url", "javascript:alert(1)", "invalid_scheme"),
        ("ref_url", "https://outside.example/items/42", "host_not_allowed"),
        ("ref_title", "title!", "invalid_characters"),
        ("ref_title", "title-is-too-long", "too_long"),
        ("description", "Ready for review\nAgain", "invalid_characters"),
        ("description", "x" * 121, "too_long"),
        ("kind", "chat", "unsupported_kind"),
    ],
)
def test_send_rejects_invalid_pointer_fields(
    tmp_path: Path, field: str, value: str, expected_issue: str
) -> None:
    service, _ = make_service(tmp_path)
    command = replace(make_command(), **{field: value})

    with pytest.raises(SendValidationError) as error:
        service.send(
            sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
            command=command,
            known_seat_ids={"seat_a", "seat_b"},
        )

    assert any(issue.code == expected_issue for issue in error.value.issues)
    assert value not in str(error.value)


def test_send_accepts_description_at_120_characters(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    command = replace(make_command(), description="x" * 120)

    result = service.send(
        sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
        command=command,
        known_seat_ids={"seat_a", "seat_b"},
    )

    assert result.pointer_id


def test_send_rejects_more_than_ten_recipients(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    recipients = tuple(f"seat_{number}" for number in range(11))

    with pytest.raises(SendValidationError) as error:
        service.send(
            sender=AuthenticatedSeat(id="sender", display_name="Ari", role="Writer"),
            command=make_command(recipients=recipients),
            known_seat_ids={"sender", *recipients},
        )

    assert any(issue.code == "too_many_recipients" for issue in error.value.issues)


def test_full_recipient_inbox_rejects_multi_recipient_send_without_partial_write(
    tmp_path: Path,
) -> None:
    service, storage = make_service(tmp_path)
    service.send(
        sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
        command=make_command(recipients=("seat_b",)),
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
    )
    service.send(
        sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
        command=make_command(recipients=("seat_b",)),
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
    )
    before = storage.snapshot()

    with pytest.raises(SendValidationError) as error:
        service.send(
            sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
            command=make_command(recipients=("seat_c", "seat_b")),
            known_seat_ids={"seat_a", "seat_b", "seat_c"},
        )

    assert any(issue.code == "recipient_inbox_full" for issue in error.value.issues)
    assert storage.snapshot() == before


def test_storage_limit_rejects_send_without_partial_write(tmp_path: Path) -> None:
    service, storage = make_service(tmp_path, max_pointer_records=2)
    for _ in range(2):
        service.send(
            sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
            command=make_command(),
            known_seat_ids={"seat_a", "seat_b"},
        )
    before = storage.snapshot()

    with pytest.raises(SendValidationError) as error:
        service.send(
            sender=AuthenticatedSeat(id="seat_a", display_name="Ari", role="Writer"),
            command=make_command(),
            known_seat_ids={"seat_a", "seat_b"},
        )

    assert any(issue.code == "storage_limit_reached" for issue in error.value.issues)
    assert storage.snapshot() == before
