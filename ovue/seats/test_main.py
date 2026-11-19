"""Check seat operations, recipient lookup, and the public seat directory."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ovue.configuration import Settings
from ovue.seats.main import (
    authenticate,
    create_seat,
    known_seat_ids,
    rename_seat,
    revoke_token,
    rotate_token,
    seat_directory,
    token_is_active,
)
from ovue.storage.seats import SeatStorage


def make_settings(tmp_path: Path) -> Settings:
    """Set capacity values that can reserve resources for one seat."""
    return Settings(
        frozenset(),
        tmp_path,
        "127.0.0.1",
        8765,
        100,
        10_000_000,
        30,
        90,
        10,
        None,
        None,
    )


def test_create_seat_preserves_global_stream_and_unread_reservations(
    tmp_path: Path,
) -> None:
    """Reject a new seat when global settings cannot reserve its minimum capacity."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    settings = make_settings(tmp_path)
    create_seat(
        storage,
        settings,
        handle="writer",
        display_name="Ese",
        role="Writer",
    )

    with pytest.raises(ValueError, match="ten deliveries"):
        create_seat(
            storage,
            settings,
            handle="reviewer",
            display_name="Ari",
            role="Reviewer",
        )

    assert len(storage.list_seats()) == 1
    storage.close()


def test_concurrent_registration_cannot_overbook_global_capacity(
    tmp_path: Path,
) -> None:
    """Serialize simultaneous seat creation against the global unread reservation."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    settings = make_settings(tmp_path)

    def register(handle: str) -> str:
        """Return a safe summary of one concurrent registration attempt."""
        try:
            create_seat(
                storage,
                settings,
                handle=handle,
                display_name=handle.title(),
                role="Writer",
            )
        except ValueError as error:
            return str(error)
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(register, ("writer", "reviewer")))

    assert sorted(outcomes) == [
        "Global unread capacity cannot reserve ten deliveries per seat",
        "created",
    ]
    assert len(storage.list_seats()) == 1
    storage.close()


def test_directory_lists_registered_seats_and_operator_without_tokens(
    tmp_path: Path,
) -> None:
    """Include the reserved operator identity without exposing credential data."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    create_seat(
        storage,
        make_settings(tmp_path),
        handle="Writer",
        display_name="Ese",
        role="Writer",
    )

    directory = seat_directory(storage)

    assert directory[0]["handle"] == "writer"
    assert directory[-1] == {
        "id": "operator",
        "handle": "operator",
        "display_name": "Operator",
        "role": "operator",
    }
    assert all("token" not in field for seat in directory for field in seat)
    storage.close()


def test_identity_and_token_operations_use_the_seats_boundary(
    tmp_path: Path,
) -> None:
    """Keep the seat ID stable through rename, revocation, and token rotation."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    seat, original_token = create_seat(
        storage,
        make_settings(tmp_path),
        handle="Writer",
        display_name="Ese",
        role="Writer",
    )

    renamed = rename_seat(storage, seat.id, "Editor")
    assert renamed.id == seat.id
    assert renamed.handle == "editor"
    assert known_seat_ids(storage) == {seat.id}
    assert authenticate(storage, original_token).id == seat.id

    revoke_token(storage, seat.id)
    assert not token_is_active(storage, seat.id, original_token)
    replacement_token = rotate_token(storage, seat.id)
    assert token_is_active(storage, seat.id, replacement_token)
    assert authenticate(storage, replacement_token).id == seat.id
    with pytest.raises(PermissionError):
        authenticate(storage, original_token)
    storage.close()
