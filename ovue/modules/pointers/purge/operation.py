"""Apply the configured pointer and traffic-log retention periods."""

from dataclasses import dataclass

from ovue.modules.pointers.storage.sqlite import SQLite


@dataclass(frozen=True)
class PurgeResult:
    """Report how many pointer rows and traffic rows were removed."""

    pointers_deleted: int
    traffic_rows_deleted: int


def purge(
    storage: SQLite,
    *,
    pointer_age_days: int,
    log_age_days: int,
    vacuum: bool = False,
) -> PurgeResult:
    """Delete only fully read old pointers and independently expired log rows."""
    if pointer_age_days < 1 or log_age_days < 1:
        raise ValueError("Retention ages must be positive")
    pointers, traffic_rows = storage.purge(
        pointer_age_days=pointer_age_days,
        log_age_days=log_age_days,
        vacuum=vacuum,
    )
    return PurgeResult(pointers, traffic_rows)
