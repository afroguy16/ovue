"""Apply the configured physical page limit to every SQLite connection."""

from __future__ import annotations

import math
import sqlite3


def apply_physical_page_limit(
    connection: sqlite3.Connection,
    logical_limit_bytes: int,
) -> int:
    """Reserve 15 percent headroom and return the enforced maximum page count."""
    if logical_limit_bytes < 1:
        raise ValueError("The logical database limit must be positive")

    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    physical_limit_bytes = math.ceil(logical_limit_bytes * 1.15)
    requested_pages = math.ceil(physical_limit_bytes / page_size)
    actual_pages = int(
        connection.execute(f"PRAGMA max_page_count = {requested_pages}").fetchone()[0]
    )
    current_pages = int(connection.execute("PRAGMA page_count").fetchone()[0])
    if actual_pages > requested_pages or current_pages > requested_pages:
        raise ValueError("The database is larger than the configured physical limit")
    return actual_pages
