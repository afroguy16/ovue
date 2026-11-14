"""Measure pointer capacity and report the contract's 80-percent warnings."""

import logging
import threading
from weakref import WeakKeyDictionary

from ovue.modules.pointers.storage.sqlite import SQLite

_WARNING_STATES: WeakKeyDictionary[SQLite, dict[str, bool]] = WeakKeyDictionary()
_WARNING_LOCK = threading.Lock()


def warn_if_near_capacity(
    storage: SQLite,
    *,
    max_pointer_records: int,
    max_logical_database_bytes: int,
) -> tuple[str, ...]:
    """Log one safe warning for each storage measure at or above eighty percent."""
    usage = storage.capacity_usage()
    warnings: list[str] = []
    if usage.pointer_records * 5 >= max_pointer_records * 4:
        warnings.append("Pointer records are at least 80% of configured capacity")
    if usage.logical_database_bytes * 5 >= max_logical_database_bytes * 4:
        warnings.append("Logical SQLite storage is at least 80% of configured capacity")
    thresholds = {
        "pointer records": usage.pointer_records * 5 >= max_pointer_records * 4,
        "logical SQLite storage": (
            usage.logical_database_bytes * 5 >= max_logical_database_bytes * 4
        ),
    }
    with _WARNING_LOCK:
        storage_states = _WARNING_STATES.setdefault(storage, {})
        for key, reached in thresholds.items():
            if reached and not storage_states.get(key, False):
                message = next(
                    warning for warning in warnings if key in warning.lower()
                )
                logging.getLogger("ovue").warning(message)
            storage_states[key] = reached
    return tuple(warnings)
