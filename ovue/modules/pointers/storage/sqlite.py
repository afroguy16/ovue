"""Persist pointer sends using serialized SQLite transactions."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class PointerRecord:
    """Hold validated pointer and authenticated sender data for persistence."""

    sender_id: str
    sender_display_name: str
    sender_role: str
    recipients: tuple[str, ...]
    ref_url: str
    ref_title: str | None
    description: str
    kind: str


@dataclass(frozen=True)
class DeliveredPointer:
    """Describe one pointer's persisted delivery to a recipient."""

    delivery_id: str
    recipient_id: str
    state: str


class CapacityReached(Exception):
    """Report storage capacity without depending on validation-layer types."""

    def __init__(self, code: str, message: str, path: tuple[str | int, ...]) -> None:
        """Keep capacity details available for translation by the send operation."""
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)


class SQLite:
    """Own pointer persistence and atomic send capacity checks."""

    def __init__(self, database_path: Path) -> None:
        """Open the database and create the tables required by pointer sending."""
        self._connection = sqlite3.connect(
            database_path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        """Create normalized pointer, delivery, and traffic-log tables."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pointers (
                pointer_id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                sender_display_name TEXT NOT NULL,
                sender_role TEXT NOT NULL,
                recipients_json TEXT NOT NULL,
                ref_url TEXT NOT NULL,
                ref_title TEXT,
                description TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id TEXT PRIMARY KEY,
                pointer_id TEXT NOT NULL REFERENCES pointers(pointer_id),
                recipient_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('unread', 'read')),
                recipient_sequence INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (recipient_id, recipient_sequence)
            );
            CREATE INDEX IF NOT EXISTS deliveries_recipient_state
                ON deliveries (recipient_id, state);
            CREATE TABLE IF NOT EXISTS traffic_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pointer_id TEXT NOT NULL,
                delivery_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                from_id TEXT NOT NULL,
                from_display_name TEXT NOT NULL,
                from_role TEXT NOT NULL,
                to_id TEXT NOT NULL,
                ref_url TEXT NOT NULL,
                ref_title TEXT,
                description TEXT NOT NULL,
                kind TEXT NOT NULL,
                state TEXT NOT NULL
            );
            """
        )

    def persist_send(
        self,
        pointer: PointerRecord,
        *,
        max_pointer_records: int,
        max_logical_database_bytes: int,
        max_unread_per_seat: int,
    ) -> tuple[str, tuple[DeliveredPointer, ...]]:
        """Check capacity and persist pointer, deliveries, and logs atomically."""
        with self._lock:
            # BEGIN IMMEDIATE prevents concurrent sends from racing on capacity.
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._set_physical_page_limit(max_logical_database_bytes)
                self._check_storage_capacity(
                    max_pointer_records,
                    max_logical_database_bytes,
                )
                self._check_recipient_capacity(
                    pointer.recipients,
                    max_unread_per_seat,
                )
                pointer_id, deliveries = self._insert_pointer(pointer)
                self._connection.execute("COMMIT")
                return pointer_id, deliveries
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def _set_physical_page_limit(self, logical_limit_bytes: int) -> None:
        """Reserve 15 percent physical headroom for recovery and maintenance writes."""
        page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
        physical_limit_bytes = math.ceil(logical_limit_bytes * 1.15)
        max_pages = math.ceil(physical_limit_bytes / page_size)
        self._connection.execute(f"PRAGMA max_page_count = {max_pages}")

    def _check_storage_capacity(
        self,
        max_pointer_records: int,
        max_logical_database_bytes: int,
    ) -> None:
        """Reject writes that would exceed configured pointer or logical-size limits."""
        pointer_count = int(
            self._connection.execute("SELECT COUNT(*) FROM pointers").fetchone()[0]
        )
        if pointer_count >= max_pointer_records:
            raise CapacityReached(
                "storage_limit_reached",
                "Pointer storage capacity is full",
                ("to",),
            )

        page_count = int(self._connection.execute("PRAGMA page_count").fetchone()[0])
        free_pages = int(
            self._connection.execute("PRAGMA freelist_count").fetchone()[0]
        )
        page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
        # Free pages do not count as used space because SQLite can reuse them.
        logical_bytes = (page_count - free_pages) * page_size
        if logical_bytes >= max_logical_database_bytes:
            raise CapacityReached(
                "storage_limit_reached",
                "Pointer storage capacity is full",
                ("to",),
            )

    def _check_recipient_capacity(
        self,
        recipients: tuple[str, ...],
        max_unread_per_seat: int,
    ) -> None:
        """Reject a send if any recipient inbox has no unread slot remaining."""
        for position, recipient_id in enumerate(recipients):
            unread_count = int(
                self._connection.execute(
                    """
                    SELECT COUNT(*) FROM deliveries
                    WHERE recipient_id = ? AND state = 'unread'
                    """,
                    (recipient_id,),
                ).fetchone()[0]
            )
            if unread_count >= max_unread_per_seat:
                raise CapacityReached(
                    "recipient_inbox_full",
                    "The recipient's inbox is full",
                    ("to", position),
                )

    def _insert_pointer(
        self,
        pointer: PointerRecord,
    ) -> tuple[str, tuple[DeliveredPointer, ...]]:
        """Insert the pointer, all recipient deliveries, and corresponding log rows."""
        pointer_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        recipients_json = json.dumps(pointer.recipients, separators=(",", ":"))
        self._connection.execute(
            """
            INSERT INTO pointers (
                pointer_id, sender_id, sender_display_name, sender_role,
                recipients_json, ref_url, ref_title, description, kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pointer_id,
                pointer.sender_id,
                pointer.sender_display_name,
                pointer.sender_role,
                recipients_json,
                pointer.ref_url,
                pointer.ref_title,
                pointer.description,
                pointer.kind,
                created_at,
            ),
        )

        deliveries: list[DeliveredPointer] = []
        for recipient_id in pointer.recipients:
            delivery_id = str(uuid4())
            sequence = int(
                self._connection.execute(
                    """
                    SELECT COALESCE(MAX(recipient_sequence), 0) + 1
                    FROM deliveries WHERE recipient_id = ?
                    """,
                    (recipient_id,),
                ).fetchone()[0]
            )
            self._connection.execute(
                """
                INSERT INTO deliveries (
                    delivery_id, pointer_id, recipient_id, state,
                    recipient_sequence, created_at
                ) VALUES (?, ?, ?, 'unread', ?, ?)
                """,
                (delivery_id, pointer_id, recipient_id, sequence, created_at),
            )
            self._connection.execute(
                """
                INSERT INTO traffic_log (
                    pointer_id, delivery_id, created_at, from_id,
                    from_display_name, from_role, to_id, ref_url, ref_title,
                    description, kind, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unread')
                """,
                (
                    pointer_id,
                    delivery_id,
                    created_at,
                    pointer.sender_id,
                    pointer.sender_display_name,
                    pointer.sender_role,
                    recipient_id,
                    pointer.ref_url,
                    pointer.ref_title,
                    pointer.description,
                    pointer.kind,
                ),
            )
            deliveries.append(
                DeliveredPointer(
                    delivery_id=delivery_id,
                    recipient_id=recipient_id,
                    state="unread",
                )
            )

        return pointer_id, tuple(deliveries)

    def snapshot(self) -> tuple[int, int, int]:
        """Return pointer, delivery, and log counts for storage tests."""
        with self._lock:
            pointer_count = int(
                self._connection.execute("SELECT COUNT(*) FROM pointers").fetchone()[0]
            )
            delivery_count = int(
                self._connection.execute("SELECT COUNT(*) FROM deliveries").fetchone()[
                    0
                ]
            )
            log_count = int(
                self._connection.execute("SELECT COUNT(*) FROM traffic_log").fetchone()[
                    0
                ]
            )
            return pointer_count, delivery_count, log_count

    def close(self) -> None:
        """Close the SQLite connection when its owner is finished with it."""
        with self._lock:
            self._connection.close()
