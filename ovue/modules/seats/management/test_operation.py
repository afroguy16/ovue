"""Check that seat creation preserves the minimum global reservations."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ovue.configuration import Settings
from ovue.modules.seats.management.operation import create_seat
from ovue.modules.seats.storage.sqlite import SeatStorage


def make_settings(tmp_path: Path) -> Settings:
    """Create settings that can reserve the required per-seat capacity."""
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


def test_create_seat_rejects_insufficient_stream_or_unread_reservation(
    tmp_path: Path,
) -> None:
    """Keep each registered seat's minimum stream and unread capacity available."""
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
    storage.close()


def test_concurrent_seat_creation_cannot_overbook_global_reservations(
    tmp_path: Path,
) -> None:
    """Serialize concurrent registrations against the global unread reservation."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    settings = make_settings(tmp_path)

    def register(handle: str) -> str:
        """Attempt a registration and return its safe outcome for the race test."""
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
        results = list(executor.map(register, ("writer", "reviewer")))

    assert sorted(results) == [
        "Global unread capacity cannot reserve ten deliveries per seat",
        "created",
    ]
    assert len(storage.list_seats()) == 1
    storage.close()
