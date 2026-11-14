"""Open the operator-owned data directory and module storage interfaces."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ovue.configuration import Settings, load_settings
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.seats.storage.sqlite import SeatStorage


@dataclass
class Stores:
    """Hold the SQLite interfaces used by one local CLI command."""

    settings: Settings
    seats: SeatStorage
    pointers: SQLite


@contextmanager
def open_stores(config_path: Path) -> Iterator[Stores]:
    """Open protected local stores and close both connections after a command."""
    settings = load_settings(config_path)
    _prepare_owned_directory(settings.data_dir, settings.database_path)
    seats = SeatStorage(settings.database_path)
    try:
        pointers = SQLite(settings.database_path)
    except Exception:
        seats.close()
        raise
    try:
        yield Stores(settings, seats, pointers)
    finally:
        pointers.close()
        seats.close()


def _prepare_owned_directory(data_dir: Path, database_path: Path) -> None:
    """Create private storage or reject paths owned by another OS user."""
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    owner_id = os.getuid()
    if data_dir.stat().st_uid != owner_id:
        raise PermissionError("The Ovue data directory must belong to this OS user")
    if database_path.exists() and database_path.stat().st_uid != owner_id:
        raise PermissionError("The Ovue database must belong to this OS user")
    os.chmod(data_dir, stat.S_IRWXU)
