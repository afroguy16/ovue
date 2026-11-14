"""Provide safe, structured access to pointer traffic history."""

import json

from ovue.modules.pointers.storage.sqlite import SQLite


def read_traffic(storage: SQLite, *, limit: int = 100) -> tuple[str, ...]:
    """Return recent traffic records as one safely escaped JSON object per line."""
    if not 1 <= limit <= 1000:
        raise ValueError("Traffic history limit must be between 1 and 1000")
    return tuple(
        json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        for record in storage.read_traffic(limit=limit)
    )
