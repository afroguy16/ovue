"""Check that the seat directory contains safe identity fields only."""

from pathlib import Path

from ovue.modules.seats.directory.operation import seat_directory
from ovue.storage.seats import SeatStorage


def test_directory_includes_operator_and_never_exposes_token_data(
    tmp_path: Path,
) -> None:
    """Return handles and roles for all seats without returning credentials."""
    storage = SeatStorage(
        tmp_path / "ovue.sqlite3", max_logical_database_bytes=1_000_000
    )
    storage.create_seat("writer", "Ese", "Writer")

    directory = seat_directory(storage)

    assert directory[-1] == {
        "id": "operator",
        "handle": "founder",
        "display_name": "Founder",
        "role": "operator",
    }
    assert directory[0]["handle"] == "writer"
    assert all("token" not in field for item in directory for field in item)
    storage.close()
