"""Return stable pages of pointer traffic for authorized operator views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from ovue.operations.utils import decode_cursor, encode_cursor
from ovue.storage.main import PointerStorage


@dataclass(frozen=True)
class TrafficPage:
    """Hold one newest-first traffic page and its optional continuation cursor."""

    items: tuple[dict[str, object], ...]
    next_cursor: str | None


def get_traffic_page(
    storage: PointerStorage,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> TrafficPage:
    """Return a stable page without exposing internal traffic-log identifiers."""
    if not 1 <= limit <= 1000:
        raise ValueError("Traffic limit must be between 1 and 1000")
    before_log_id = decode_cursor(cursor) if cursor is not None else None
    rows = storage.read_traffic(
        limit=limit + 1,
        before_log_id=before_log_id,
    )
    has_more = len(rows) > limit
    visible_rows = rows[:limit]
    next_cursor = (
        encode_cursor(cast(int, visible_rows[-1]["_log_id"])) if has_more else None
    )
    items = tuple(
        {key: value for key, value in row.items() if key != "_log_id"}
        for row in visible_rows
    )
    return TrafficPage(items=items, next_cursor=next_cursor)
