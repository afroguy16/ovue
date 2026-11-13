"""Pure transformations used by pointer validation."""

from __future__ import annotations

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
