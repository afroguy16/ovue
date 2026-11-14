"""Check durable seat identity, token safety, and token lifecycle behavior."""

import sqlite3
import stat
from pathlib import Path

import pytest

from ovue.modules.seats.storage.sqlite import SeatStorage


def test_create_seat_returns_one_time_token_and_stores_only_its_hash(
    tmp_path: Path,
) -> None:
    """Return the raw token once while persisting only a one-way digest."""
    database_path = tmp_path / "ovue.sqlite3"
    storage = SeatStorage(database_path, max_logical_database_bytes=1_000_000)

    seat, token = storage.create_seat("Writer-1", "Ese", "Writer")

    assert seat.handle == "writer-1"
    assert storage.authenticate(token).id == seat.id
    with sqlite3.connect(database_path) as connection:
        saved_hash = connection.execute(
            "SELECT token_hash FROM seat_tokens WHERE seat_id = ?", (seat.id,)
        ).fetchone()[0]
    assert token not in saved_hash
    assert len(saved_hash) == 64
    storage.close()


def test_handle_uniqueness_is_case_insensitive(tmp_path: Path) -> None:
    """Reject a second seat when its handle differs only by letter case."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    storage.create_seat("Researcher", "Ada", "Researcher")

    with pytest.raises(ValueError, match="already in use"):
        storage.create_seat("RESEARCHER", "Ari", "Writer")
    storage.close()


def test_handle_lookup_is_case_insensitive(tmp_path: Path) -> None:
    """Find the same seat regardless of the letter case used for its handle."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    created, _ = storage.create_seat("Researcher", "Ada", "Researcher")

    found = storage.get_by_handle("RESEARCHER")

    assert found.id == created.id
    assert found.handle == "researcher"
    storage.close()


def test_seat_database_and_parent_directory_are_private(tmp_path: Path) -> None:
    """Restrict the local database file and its data directory to the owner."""
    database_path = tmp_path / "private" / "ovue.sqlite3"
    storage = SeatStorage(database_path, max_logical_database_bytes=1_000_000)

    assert stat.S_IMODE(database_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    storage.close()


def test_seat_connection_applies_the_shared_physical_database_limit(
    tmp_path: Path,
) -> None:
    """Cap seat writes using the same reserved headroom as pointer writes."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3",
        max_logical_database_bytes=100_000,
    )

    page_limit = int(storage._connection.execute("PRAGMA max_page_count").fetchone()[0])
    page_count = int(storage._connection.execute("PRAGMA page_count").fetchone()[0])

    assert page_limit > page_count
    storage.close()


def test_token_rotation_invalidates_the_old_token_immediately(
    tmp_path: Path,
) -> None:
    """Make only the replacement token usable after a rotation commits."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    seat, old_token = storage.create_seat("writer", "Ese", "Writer")

    new_token = storage.rotate_token(seat.id)

    with pytest.raises(PermissionError):
        storage.authenticate(old_token)
    assert storage.authenticate(new_token).id == seat.id
    storage.close()


def test_revoked_token_can_be_rotated_back_to_a_usable_token(
    tmp_path: Path,
) -> None:
    """Allow a revoked seat to receive a new token without changing its ID."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    seat, old_token = storage.create_seat("writer", "Ese", "Writer")
    storage.revoke_token(seat.id)

    new_token = storage.rotate_token(seat.id)

    assert storage.authenticate(new_token).id == seat.id
    with pytest.raises(PermissionError):
        storage.authenticate(old_token)
    storage.close()


def test_rename_keeps_seat_id_and_token_usable(tmp_path: Path) -> None:
    """Change only the handle while preserving identity and authentication."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    seat, token = storage.create_seat("writer", "Ese", "Writer")

    renamed = storage.rename_handle(seat.id, "editor")

    assert renamed.id == seat.id
    assert renamed.handle == "editor"
    assert storage.authenticate(token).id == seat.id
    storage.close()


def test_reserved_founder_handle_cannot_be_created_or_assigned(
    tmp_path: Path,
) -> None:
    """Keep the operator's identity from being claimed by a registered seat."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    with pytest.raises(ValueError, match="reserved"):
        storage.create_seat("founder", "Other", "Writer")
    seat, _ = storage.create_seat("writer", "Ese", "Writer")

    with pytest.raises(ValueError, match="reserved"):
        storage.rename_handle(seat.id, "Founder")
    storage.close()
