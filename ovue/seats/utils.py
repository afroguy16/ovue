"""Validate and normalize human-readable seat handles."""

from __future__ import annotations

import re

_HANDLE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,31}\Z")


def normalize_handle(value: str) -> str:
    """Return a normalized handle or raise ValueError when it is invalid."""
    if not _HANDLE_PATTERN.fullmatch(value):
        raise ValueError("Handle must be 2–32 ASCII letters, digits, _ or -")
    normalized = value.lower()
    if normalized == "operator":
        raise ValueError("The handle operator is reserved")
    return normalized
