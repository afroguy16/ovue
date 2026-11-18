"""Handle operator-only traffic history and retention commands."""

from typing import TextIO

from ovue.cli.context import Stores
from ovue.operations.main import purge, read_traffic


def traffic(stores: Stores, output: TextIO, *, limit: int) -> None:
    """Write recent traffic records as one escaped JSON object per line."""
    for line in read_traffic(stores.pointers, limit=limit):
        print(line, file=output)


def purge_history(stores: Stores, output: TextIO, *, vacuum: bool) -> None:
    """Run the configured pointer and traffic-log retention operation."""
    result = purge(
        stores.pointers,
        pointer_age_days=stores.settings.pointer_age_days,
        log_age_days=stores.settings.log_age_days,
        vacuum=vacuum,
    )
    print(
        f"Deleted {result.pointers_deleted} pointers and "
        f"{result.traffic_rows_deleted} traffic rows",
        file=output,
    )
