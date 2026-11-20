"""Check cursor pagination over the operator's pointer traffic history."""

from pathlib import Path
from typing import cast

import pytest

from ovue.operations.traffic import get_traffic_page
from ovue.storage.main import PointerRecord, SQLite


def save_pointer(storage: SQLite, title: str) -> None:
    """Create one traffic record with a title that identifies its position."""
    storage.persist_send(
        PointerRecord(
            sender_id="seat_a",
            sender_display_name="Ari",
            sender_role="Writer",
            recipients=("seat_b",),
            ref_url="https://work.example.org/items/42",
            ref_title=title,
            description=f"Pointer {title}",
            kind="info",
        ),
        max_pointer_records=100,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=100,
    )


def test_traffic_pages_reach_older_rows_without_duplicates_when_new_rows_arrive(
    tmp_path: Path,
) -> None:
    """Keep page order stable when a new pointer is sent between page reads."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3",
        max_logical_database_bytes=1_000_000,
    )
    for title in ("first", "second", "third"):
        save_pointer(storage, title)

    first_page = get_traffic_page(storage, limit=2)
    save_pointer(storage, "newest")
    second_page = get_traffic_page(
        storage,
        limit=2,
        cursor=first_page.next_cursor,
    )

    assert [
        cast(dict[str, object], item["ref"])["title"] for item in first_page.items
    ] == [
        "third",
        "second",
    ]
    assert [
        cast(dict[str, object], item["ref"])["title"] for item in second_page.items
    ] == ["first"]
    assert second_page.next_cursor is None
    assert all("_log_id" not in item for item in first_page.items)
    storage.close()


@pytest.mark.parametrize("limit", [0, 1001])
def test_traffic_page_rejects_limits_outside_the_supported_range(
    limit: int,
    tmp_path: Path,
) -> None:
    """Reject empty and unbounded operator traffic pages."""
    storage = SQLite(
        tmp_path / "pointers.sqlite3",
        max_logical_database_bytes=1_000_000,
    )

    with pytest.raises(ValueError, match="between 1 and 1000"):
        get_traffic_page(storage, limit=limit)

    storage.close()
