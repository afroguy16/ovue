"""Pure transformations used by pointer validation."""

from __future__ import annotations

import base64
import binascii
from urllib.parse import SplitResult, urlsplit


def unique_in_order(values: tuple[str, ...]) -> tuple[str, ...]:
    """Return each string once while preserving its first-seen position."""
    return tuple(dict.fromkeys(values))


def split_url(value: str) -> SplitResult | None:
    """Parse a URL into standard parts, returning None when its syntax is invalid."""
    try:
        return urlsplit(value)
    except ValueError:
        return None


def is_printable_ascii(value: str) -> bool:
    """Return whether every character is within printable ASCII U+0020–U+007E."""
    return all(" " <= character <= "~" for character in value)


def encode_cursor(sequence: int) -> str:
    """Encode an event sequence as an opaque inbox pagination cursor."""
    return (
        base64.urlsafe_b64encode(str(sequence).encode("ascii"))
        .decode("ascii")
        .rstrip("=")
    )


def decode_cursor(cursor: str) -> int:
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
