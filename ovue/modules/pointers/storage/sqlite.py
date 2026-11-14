"""Persist pointer sends using serialized SQLite transactions."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ovue.database import apply_physical_page_limit


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


@dataclass(frozen=True)
class StorageUsage:
    """Report the pointer-row count and reusable-page-aware logical size."""

    pointer_records: int
    logical_database_bytes: int


class CapacityReached(Exception):
    """Report storage capacity without depending on validation-layer types."""

    def __init__(
        self,
        code: str,
        message: str,
        path: tuple[str | int, ...],
        max_value: int | None = None,
    ) -> None:
        """Keep capacity details available for translation by the send operation."""
        self.code = code
        self.message = message
        self.path = path
        self.max_value = max_value
        super().__init__(message)


class SQLite:
    """Own pointer persistence and atomic send capacity checks."""

    def __init__(
        self,
        database_path: Path,
        *,
        max_logical_database_bytes: int,
    ) -> None:
        """Open the database and create the tables required by pointer sending."""
        self._connection = sqlite3.connect(
            database_path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        try:
            self._create_schema()
            apply_physical_page_limit(
                self._connection,
                max_logical_database_bytes,
            )
        except Exception:
            self._connection.close()
            raise

    def _create_schema(self) -> None:
        """Create normalized pointer, delivery, and traffic-log tables."""
        self._connection.execute("PRAGMA foreign_keys = ON")
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
            CREATE TABLE IF NOT EXISTS recipient_sequences (
                recipient_id TEXT PRIMARY KEY,
                last_sequence INTEGER NOT NULL
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
        self._connection.execute(
            """
            INSERT OR IGNORE INTO recipient_sequences (recipient_id, last_sequence)
            SELECT recipient_id, MAX(recipient_sequence)
            FROM deliveries GROUP BY recipient_id
            """
        )

    def persist_send(
        self,
        pointer: PointerRecord,
        *,
        max_pointer_records: int,
        max_logical_database_bytes: int,
        max_unread_per_seat: int,
        max_unread_global: int = 1000,
    ) -> tuple[str, tuple[DeliveredPointer, ...]]:
        """Check capacity and persist pointer, deliveries, and logs atomically."""
        with self._lock:
            # BEGIN IMMEDIATE prevents concurrent sends from racing on capacity.
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                apply_physical_page_limit(
                    self._connection,
                    max_logical_database_bytes,
                )
                self._check_storage_capacity(
                    max_pointer_records,
                    max_logical_database_bytes,
                )
                self._check_recipient_capacity(
                    pointer.recipients,
                    max_unread_per_seat,
                )
                self._check_global_unread_capacity(
                    pointer.recipients,
                    max_unread_global,
                )
                pointer_id, deliveries = self._insert_pointer(pointer)
                self._check_logical_database_capacity(max_logical_database_bytes)
                self._connection.execute("COMMIT")
                return pointer_id, deliveries
            except sqlite3.OperationalError as error:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                if "full" in str(error).lower():
                    raise CapacityReached(
                        "storage_limit_reached",
                        "Pointer storage capacity is full",
                        ("to",),
                    ) from None
                raise
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

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

        self._check_logical_database_capacity(
            max_logical_database_bytes,
            reject_equal=True,
        )

    def _check_logical_database_capacity(
        self,
        limit_bytes: int,
        *,
        reject_equal: bool = False,
    ) -> None:
        """Reject a database write whose used pages exceed the logical cap."""
        page_count = int(self._connection.execute("PRAGMA page_count").fetchone()[0])
        free_pages = int(
            self._connection.execute("PRAGMA freelist_count").fetchone()[0]
        )
        page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
        # Free pages do not count as used space because SQLite can reuse them.
        logical_bytes = (page_count - free_pages) * page_size
        over_limit = (
            logical_bytes >= limit_bytes
            if reject_equal
            else logical_bytes > limit_bytes
        )
        if over_limit:
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
                    max_unread_per_seat,
                )

    def _check_global_unread_capacity(
        self,
        recipients: tuple[str, ...],
        max_unread_global: int,
    ) -> None:
        """Preserve ten unread slots for each registered seat within the global cap."""
        unread_total = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM deliveries WHERE state = 'unread'"
            ).fetchone()[0]
        )
        counts: dict[str, int] = {}
        try:
            seat_ids = self._connection.execute("SELECT seat_id FROM seats").fetchall()
        except sqlite3.OperationalError:
            seat_ids = []
        for row in seat_ids:
            seat_id = str(row[0])
            counts[seat_id] = int(
                self._connection.execute(
                    """
                    SELECT COUNT(*) FROM deliveries
                    WHERE recipient_id = ? AND state = 'unread'
                    """,
                    (seat_id,),
                ).fetchone()[0]
            )
        recipients_set = set(recipients)
        registered_after = sum(
            max(10, counts[seat_id] + int(seat_id in recipients_set))
            for seat_id in counts
        )
        unregistered_after = (
            unread_total - sum(counts.values()) + len(recipients_set.difference(counts))
        )
        if registered_after + unregistered_after > max_unread_global:
            raise CapacityReached(
                "global_inbox_full",
                "Global unread delivery capacity is full",
                ("to", 0),
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
            sequence_row = self._connection.execute(
                "SELECT last_sequence FROM recipient_sequences WHERE recipient_id = ?",
                (recipient_id,),
            ).fetchone()
            sequence = 1 if sequence_row is None else int(sequence_row[0]) + 1
            self._connection.execute(
                """
                INSERT INTO recipient_sequences (recipient_id, last_sequence)
                VALUES (?, ?)
                ON CONFLICT(recipient_id)
                DO UPDATE SET last_sequence = excluded.last_sequence
                """,
                (recipient_id, sequence),
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

    def capacity_usage(self) -> StorageUsage:
        """Measure current pointer rows and logical SQLite bytes for warnings."""
        with self._lock:
            pointer_count = int(
                self._connection.execute("SELECT COUNT(*) FROM pointers").fetchone()[0]
            )
            page_count = int(
                self._connection.execute("PRAGMA page_count").fetchone()[0]
            )
            free_pages = int(
                self._connection.execute("PRAGMA freelist_count").fetchone()[0]
            )
            page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
            return StorageUsage(
                pointer_count,
                (page_count - free_pages) * page_size,
            )

    def get_inbox(
        self,
        recipient_id: str,
        *,
        unread: bool | None,
        after_sequence: int,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        """Return one recipient's pointer deliveries after its sequence cursor."""
        state_clause = "" if unread is None else "AND d.state = ?"
        values: tuple[object, ...] = (recipient_id, after_sequence)
        if unread is not None:
            values += ("unread" if unread else "read",)
        values += (limit,)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT d.recipient_sequence, d.delivery_id, d.state, d.created_at,
                       p.pointer_id, p.sender_id, p.sender_display_name, p.sender_role,
                       p.recipients_json, p.ref_url, p.ref_title, p.description, p.kind
                FROM deliveries AS d
                JOIN pointers AS p USING (pointer_id)
                WHERE d.recipient_id = ? AND d.recipient_sequence > ? {state_clause}
                ORDER BY d.recipient_sequence ASC
                LIMIT ?
                """,
                values,
            ).fetchall()
            return tuple(self._delivery_view(row) for row in rows)

    def acknowledge_delivery(self, delivery_id: str, recipient_id: str) -> None:
        """Mark one owned delivery read, hiding foreign and missing IDs alike."""
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT pointer_id FROM deliveries "
                    "WHERE delivery_id = ? AND recipient_id = ?",
                    (delivery_id, recipient_id),
                ).fetchone()
                if row is None:
                    raise LookupError("Delivery not found")
                self._connection.execute(
                    "UPDATE deliveries SET state = 'read' WHERE delivery_id = ?",
                    (delivery_id,),
                )
                self._connection.execute(
                    "UPDATE traffic_log SET state = 'read' WHERE delivery_id = ?",
                    (delivery_id,),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def latest_sequence(self, recipient_id: str) -> int:
        """Return the latest issued event sequence for one recipient."""
        with self._lock:
            row = self._connection.execute(
                "SELECT last_sequence FROM recipient_sequences WHERE recipient_id = ?",
                (recipient_id,),
            ).fetchone()
            return 0 if row is None else int(row[0])

    def initial_stream_state(
        self,
        recipient_id: str,
        unread_limit: int = 100,
    ) -> tuple[tuple[dict[str, object], ...], int]:
        """Read unread backlog and latest sequence from one consistent snapshot."""
        with self._lock:
            self._connection.execute("BEGIN")
            try:
                backlog = self.get_inbox(
                    recipient_id,
                    unread=True,
                    after_sequence=0,
                    limit=unread_limit + 1,
                )
                latest = self.latest_sequence(recipient_id)
                self._connection.execute("COMMIT")
                return backlog, latest
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def replay_after(
        self,
        recipient_id: str,
        sequence: int,
        *,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        """Return retained events after a recipient's validated sequence cursor."""
        with self._lock:
            latest = self.latest_sequence(recipient_id)
            if sequence > latest:
                raise ValueError("Event cursor is ahead of the newest event")
            row = self._connection.execute(
                "SELECT MIN(recipient_sequence) FROM deliveries WHERE recipient_id = ?",
                (recipient_id,),
            ).fetchone()
            earliest = row[0]
            if earliest is not None and sequence < int(earliest) - 1:
                raise RuntimeError("Replay is no longer retained")
            if earliest is None and sequence < latest:
                raise RuntimeError("Replay is no longer retained")
            events = self.get_inbox(
                recipient_id,
                unread=None,
                after_sequence=sequence,
                limit=limit + 1,
            )
            if len(events) > limit:
                raise RuntimeError("Replay exceeds the event limit")
            return events

    def read_traffic(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        """Return recent traffic records in creation order for the operator."""
        if not 1 <= limit <= 1000:
            raise ValueError("Traffic limit must be between 1 and 1000")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT pointer_id, delivery_id, created_at, from_id, from_display_name,
                       from_role, to_id, ref_url, ref_title, description, kind, state
                FROM traffic_log ORDER BY log_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        records = []
        for row in reversed(rows):
            records.append(
                {
                    "pointer_id": row["pointer_id"],
                    "delivery_id": row["delivery_id"],
                    "created_at": row["created_at"],
                    "from": {
                        "id": row["from_id"],
                        "display_name": row["from_display_name"],
                        "role": row["from_role"],
                    },
                    "to": row["to_id"],
                    "ref": {"url": row["ref_url"], "title": row["ref_title"]},
                    "description": row["description"],
                    "kind": row["kind"],
                    "state": row["state"],
                }
            )
        return tuple(records)

    def purge(
        self,
        *,
        pointer_age_days: int,
        log_age_days: int,
        vacuum: bool = False,
        now: datetime | None = None,
    ) -> tuple[int, int]:
        """Delete eligible pointers and independently expired traffic records."""
        if pointer_age_days < 1 or log_age_days < 1:
            raise ValueError("Retention ages must be positive")
        current = now or datetime.now(UTC)
        pointer_cutoff = (current - timedelta(days=pointer_age_days)).isoformat()
        log_cutoff = (current - timedelta(days=log_age_days)).isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                eligible = self._connection.execute(
                    """
                    SELECT p.pointer_id FROM pointers AS p
                    WHERE p.created_at <= ?
                      AND NOT EXISTS (
                          SELECT 1 FROM deliveries AS d
                          WHERE d.pointer_id = p.pointer_id AND d.state = 'unread'
                      )
                    """,
                    (pointer_cutoff,),
                ).fetchall()
                pointer_ids = tuple(str(row[0]) for row in eligible)
                for pointer_id in pointer_ids:
                    self._connection.execute(
                        "DELETE FROM deliveries WHERE pointer_id = ?", (pointer_id,)
                    )
                    self._connection.execute(
                        "DELETE FROM pointers WHERE pointer_id = ?", (pointer_id,)
                    )
                pointer_count = len(pointer_ids)
                cursor = self._connection.execute(
                    "DELETE FROM traffic_log WHERE created_at <= ?", (log_cutoff,)
                )
                log_count = cursor.rowcount
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            if vacuum:
                self._connection.execute("VACUUM")
            return pointer_count, log_count

    @staticmethod
    def _delivery_view(row: sqlite3.Row) -> dict[str, object]:
        """Build the self-contained representation used by inbox and stream events."""
        return {
            "event_id": int(row["recipient_sequence"]),
            "delivery_id": row["delivery_id"],
            "pointer_id": row["pointer_id"],
            "created_at": row["created_at"],
            "from": {
                "id": row["sender_id"],
                "display_name": row["sender_display_name"],
                "role": row["sender_role"],
            },
            "to": json.loads(row["recipients_json"]),
            "ref": {"url": row["ref_url"], "title": row["ref_title"]},
            "description": row["description"],
            "kind": row["kind"],
            "state": row["state"],
        }

    def close(self) -> None:
        """Close the SQLite connection when its owner is finished with it."""
        with self._lock:
            self._connection.close()
