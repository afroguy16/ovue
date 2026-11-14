"""Persist seat identities and hashed bearer-token state in SQLite."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ovue.modules.seats.entities import AuthenticatedSeat, Seat
from ovue.modules.seats.handles.validation import normalize_handle


class SeatStorage:
    """Own seat and token persistence for one Ovue database."""

    def __init__(self, database_path: Path) -> None:
        """Open a private database and create the seat tables if needed."""
        database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(database_path.parent, 0o700)
        previous_umask = os.umask(0o077)
        try:
            self._connection = sqlite3.connect(
                database_path,
                isolation_level=None,
                check_same_thread=False,
                timeout=10,
            )
        finally:
            os.umask(previous_umask)
        os.chmod(database_path, 0o600)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        """Create the registered-seat and current-token tables."""
        self._connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS seats (
                seat_id TEXT PRIMARY KEY,
                handle TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seat_tokens (
                seat_id TEXT PRIMARY KEY REFERENCES seats(seat_id),
                token_hash TEXT,
                revoked_at TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )

    def create_seat(
        self,
        handle: str,
        display_name: str,
        role: str,
        *,
        max_streams_global: int | None = None,
        max_unread_global: int | None = None,
    ) -> tuple[Seat, str]:
        """Create a seat and return its newly issued token exactly once."""
        normalized_handle = normalize_handle(handle)
        seat_id = str(uuid4())
        token = secrets.token_urlsafe(32)
        timestamp = datetime.now(UTC).isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                if max_streams_global is not None or max_unread_global is not None:
                    next_seat_count = (
                        int(
                            self._connection.execute(
                                "SELECT COUNT(*) FROM seats"
                            ).fetchone()[0]
                        )
                        + 1
                    )
                    if (
                        max_streams_global is not None
                        and max_streams_global < next_seat_count
                    ):
                        raise ValueError(
                            "Global stream capacity cannot reserve one stream per seat"
                        )
                    if (
                        max_unread_global is not None
                        and max_unread_global < next_seat_count * 10
                    ):
                        raise ValueError(
                            "Global unread capacity cannot reserve ten deliveries "
                            "per seat"
                        )
                self._connection.execute(
                    "INSERT INTO seats VALUES (?, ?, ?, ?, ?)",
                    (seat_id, normalized_handle, display_name, role, timestamp),
                )
                self._connection.execute(
                    "INSERT INTO seat_tokens VALUES (?, ?, NULL, ?)",
                    (seat_id, self._token_hash(token), timestamp),
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                self._connection.execute("ROLLBACK")
                if "handle" in str(error).lower():
                    raise ValueError("Handle is already in use") from None
                raise
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return Seat(seat_id, normalized_handle, display_name, role, True), token

    def list_seats(self) -> tuple[Seat, ...]:
        """Return every seat and whether its current token is active."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT seats.*, seat_tokens.revoked_at
                FROM seats JOIN seat_tokens USING (seat_id)
                ORDER BY seats.created_at, seats.seat_id
                """
            ).fetchall()
        return tuple(
            Seat(
                row["seat_id"],
                row["handle"],
                row["display_name"],
                row["role"],
                row["revoked_at"] is None,
            )
            for row in rows
        )

    def known_seat_ids(self) -> set[str]:
        """Return registered IDs for pointer recipient validation."""
        with self._lock:
            rows = self._connection.execute("SELECT seat_id FROM seats").fetchall()
        return {str(row[0]) for row in rows}

    def get_seat(self, seat_id: str) -> Seat:
        """Return one seat or raise KeyError when its ID is not registered."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT seats.*, seat_tokens.revoked_at
                FROM seats JOIN seat_tokens USING (seat_id)
                WHERE seats.seat_id = ?
                """,
                (seat_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Seat not found")
        return Seat(
            row["seat_id"],
            row["handle"],
            row["display_name"],
            row["role"],
            row["revoked_at"] is None,
        )

    def get_by_handle(self, handle: str) -> Seat:
        """Find one seat by its case-insensitive normalized handle."""
        normalized_handle = normalize_handle(handle)
        with self._lock:
            row = self._connection.execute(
                """
                SELECT seats.*, seat_tokens.revoked_at
                FROM seats JOIN seat_tokens USING (seat_id)
                WHERE seats.handle = ? COLLATE NOCASE
                """,
                (normalized_handle,),
            ).fetchone()
        if row is None:
            raise KeyError("Seat not found")
        return Seat(
            row["seat_id"],
            row["handle"],
            row["display_name"],
            row["role"],
            row["revoked_at"] is None,
        )

    def rename_handle(self, seat_id: str, handle: str) -> Seat:
        """Rename a seat's handle without changing its ID or token."""
        normalized_handle = normalize_handle(handle)
        with self._lock:
            try:
                cursor = self._connection.execute(
                    "UPDATE seats SET handle = ? WHERE seat_id = ?",
                    (normalized_handle, seat_id),
                )
            except sqlite3.IntegrityError:
                raise ValueError("Handle is already in use") from None
        if cursor.rowcount == 0:
            raise KeyError("Seat not found")
        return self.get_seat(seat_id)

    def revoke_token(self, seat_id: str) -> None:
        """Invalidate the current token while keeping the seat registered."""
        timestamp = datetime.now(UTC).isoformat()
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE seat_tokens
                SET token_hash = NULL, revoked_at = ?, updated_at = ?
                WHERE seat_id = ?
                """,
                (timestamp, timestamp, seat_id),
            )
        if cursor.rowcount == 0:
            raise KeyError("Seat not found")

    def rotate_token(self, seat_id: str) -> str:
        """Issue a replacement token and revoke the prior token atomically."""
        token = secrets.token_urlsafe(32)
        timestamp = datetime.now(UTC).isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    """
                    UPDATE seat_tokens
                    SET token_hash = ?, revoked_at = NULL, updated_at = ?
                    WHERE seat_id = ?
                    """,
                    (self._token_hash(token), timestamp, seat_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError("Seat not found")
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return token

    def authenticate(self, token: str) -> AuthenticatedSeat:
        """Resolve a bearer token with a constant-time hash comparison."""
        supplied_hash = self._token_hash(token)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT seats.seat_id, seats.handle, seats.display_name, seats.role,
                       seat_tokens.token_hash
                FROM seats JOIN seat_tokens USING (seat_id)
                WHERE seat_tokens.revoked_at IS NULL
                  AND seat_tokens.token_hash IS NOT NULL
                """
            ).fetchall()
        matched: sqlite3.Row | None = None
        compared = False
        for row in rows:
            is_match = hmac.compare_digest(str(row["token_hash"]), supplied_hash)
            compared = True
            if is_match:
                matched = row
        if not compared:
            hmac.compare_digest(self._token_hash("invalid-token"), supplied_hash)
        if matched is None:
            raise PermissionError("Invalid bearer token")
        return AuthenticatedSeat(
            matched["seat_id"],
            matched["handle"],
            matched["display_name"],
            matched["role"],
        )

    def is_token_active(self, seat_id: str, token: str) -> bool:
        """Check whether a stream's original token remains active."""
        supplied_hash = self._token_hash(token)
        with self._lock:
            row = self._connection.execute(
                "SELECT token_hash, revoked_at FROM seat_tokens WHERE seat_id = ?",
                (seat_id,),
            ).fetchone()
        stored_hash = (
            "0" * 64
            if row is None or row["token_hash"] is None
            else str(row["token_hash"])
        )
        matches = hmac.compare_digest(stored_hash, supplied_hash)
        return row is not None and row["revoked_at"] is None and matches

    def close(self) -> None:
        """Close the database connection owned by this seat store."""
        with self._lock:
            self._connection.close()

    @staticmethod
    def _token_hash(token: str) -> str:
        """Return the fixed-length digest stored for a raw bearer token."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
