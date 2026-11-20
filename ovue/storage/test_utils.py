"""Check the shared SQLite page-capacity helper."""

import math
import sqlite3

import pytest

from ovue.storage.utils import apply_physical_page_limit


def test_page_limit_reserves_fifteen_percent_headroom() -> None:
    """Set SQLite's maximum page count above the configured logical limit."""
    connection = sqlite3.connect(":memory:")
    logical_limit = 1_000_000

    maximum_pages = apply_physical_page_limit(connection, logical_limit)

    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    minimum_physical_limit = math.ceil(logical_limit * 1.15)
    assert maximum_pages * page_size >= minimum_physical_limit
    configured_pages = int(connection.execute("PRAGMA max_page_count").fetchone()[0])
    assert configured_pages == maximum_pages
    connection.close()


def test_page_limit_rejects_a_non_positive_logical_limit() -> None:
    """Reject zero because it cannot define a usable database capacity."""
    connection = sqlite3.connect(":memory:")

    with pytest.raises(ValueError, match="logical database limit must be positive"):
        apply_physical_page_limit(connection, 0)

    connection.close()
