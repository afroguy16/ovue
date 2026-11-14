"""Apply inbox filters and opaque cursor pagination."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import cast

from ovue.modules.pointers.storage.sqlite import SQLite


@dataclass(frozen=True)
class InboxPage:
    """Hold one inbox page and its optional continuation cursor."""

    items: tuple[dict[str, object], ...]
    next_cursor: str | None


def get_inbox(
    storage: SQLite,
    seat_id: str,
    *,
    unread: bool | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> InboxPage:
    """Return a filtered inbox page without exposing cursor internals to clients."""
    if not 1 <= limit <= 100:
        raise ValueError("Inbox limit must be between 1 and 100")
    after_sequence = _decode_cursor(cursor) if cursor is not None else 0
    if after_sequence > storage.latest_sequence(seat_id):
        raise ValueError("Inbox cursor is invalid")
    rows = storage.get_inbox(
        seat_id,
        unread=unread,
        after_sequence=after_sequence,
        limit=limit + 1,
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = _encode_cursor(cast(int, items[-1]["event_id"])) if has_more else None
    return InboxPage(items, next_cursor)


def _encode_cursor(sequence: int) -> str:
    """Encode a sequence for use as an opaque HTTP pagination cursor."""
    return (
        base64.urlsafe_b64encode(str(sequence).encode("ascii"))
        .decode("ascii")
        .rstrip("=")
    )


def _decode_cursor(cursor: str) -> int:
    """Decode a cursor and reject malformed or negative sequence values."""
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded_cursor, altchars=b"-_", validate=True)
        sequence = int(decoded.decode("ascii"))
    except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError, ValueError):
        raise ValueError("Inbox cursor is invalid") from None
    if not decoded.isascii() or not decoded.isdigit() or sequence < 0:
        raise ValueError("Inbox cursor is invalid")
    return sequence
