"""SQLite persistence for Ovue seats, messages, and deliveries."""

# Import hashing and random-salt helpers from the standard library.
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

# Import the domain values used by storage methods.
from ovue.services.messages import MessageInput


class Storage:
    """Own the SQLite connection and all persistence transactions."""

    # Store the SQLite database connection for this service instance.
    def __init__(self, database_path: Path) -> None:
        # Remember the path so the CLI and server share the same database.
        self.database_path = database_path
        # Open SQLite with a timeout for short concurrent-writer contention.
        self.connection = sqlite3.connect(database_path, check_same_thread=False, timeout=5)
        # Return rows that can be accessed by column name.
        self.connection.row_factory = sqlite3.Row
        # Enable foreign-key enforcement for message relationships.
        self.connection.execute("PRAGMA foreign_keys = ON")
        # Create the schema before any caller uses the store.
        self._create_schema()

    def _create_schema(self) -> None:
        """Create all MVP tables if they do not already exist."""

        # Create seats, messages, deliveries, and per-seat sequence counters together.
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS seats (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                token_salt BLOB,
                token_hash BLOB,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                ref_url TEXT NOT NULL,
                ref_title TEXT,
                description TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deliveries (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id),
                recipient_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('unread', 'read')),
                created_at TEXT NOT NULL,
                UNIQUE (recipient_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS recipient_sequences (
                recipient_id TEXT PRIMARY KEY,
                next_sequence INTEGER NOT NULL
            );
            """
        )
        # Commit schema creation so another process can observe it.
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a caller's operation in one SQLite transaction."""

        # Begin an immediate transaction to serialize MVP writers.
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            # Yield the connection so the caller performs atomic writes.
            yield self.connection
        except Exception:
            # Roll back every partial write when anything fails.
            self.connection.rollback()
            raise
        else:
            # Commit only after every write in the operation succeeds.
            self.connection.commit()

    def create_seat(self, seat_id: str, display_name: str, role: str) -> str:
        """Create a seat and return its one-time raw bearer token."""

        # Generate a token with 256 bits of randomness.
        raw_token = secrets.token_urlsafe(32)
        # Generate an independent salt for the stored token hash.
        token_salt = secrets.token_bytes(16)
        # Hash the raw token with a deliberately expensive password hash.
        token_hash = _hash_token(raw_token, token_salt)
        # Create the server timestamp in UTC.
        created_at = _utc_now()
        # Insert the seat and token hash atomically.
        with self.transaction() as connection:
            # Reserve the operator identity permanently.
            if seat_id == "operator":
                raise ValueError("The operator seat ID is reserved")
            # Insert the new seat without storing the raw token.
            connection.execute(
                """
                INSERT INTO seats (id, display_name, role, token_salt, token_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (seat_id, display_name, role, token_salt, token_hash, created_at),
            )
        # Return the raw token exactly once to the caller.
        return raw_token

    def rotate_token(self, seat_id: str) -> str:
        """Replace a seat token and return the new raw token once."""

        # Generate a replacement token and salt.
        raw_token = secrets.token_urlsafe(32)
        token_salt = secrets.token_bytes(16)
        token_hash = _hash_token(raw_token, token_salt)
        # Replace the stored credential atomically.
        with self.transaction() as connection:
            # Update only a non-revoked registered seat.
            result = connection.execute(
                """
                UPDATE seats
                SET token_salt = ?, token_hash = ?, revoked = 0
                WHERE id = ? AND revoked = 0
                """,
                (token_salt, token_hash, seat_id),
            )
            # Refuse rotation when the seat does not exist or is already revoked.
            if result.rowcount != 1:
                raise ValueError("Seat does not exist or is revoked")
        # Return the raw replacement token exactly once.
        return raw_token

    def revoke_token(self, seat_id: str) -> None:
        """Revoke a seat token."""

        # Mark the token unusable in one committed update.
        with self.transaction() as connection:
            # Revoke only the requested seat.
            result = connection.execute("UPDATE seats SET revoked = 1 WHERE id = ?", (seat_id,))
            # Report a clear failure for an unknown seat.
            if result.rowcount != 1:
                raise ValueError("Seat does not exist")

    def authenticate(self, raw_token: str) -> sqlite3.Row | None:
        """Return the active seat for a bearer token, if one matches."""

        # Load all active credentials so the caller never needs raw tokens.
        rows = self.connection.execute(
            "SELECT * FROM seats WHERE revoked = 0 AND token_hash IS NOT NULL"
        ).fetchall()
        # Compare the supplied token against every active hash.
        for row in rows:
            # Recompute the hash with the stored salt.
            candidate = _hash_token(raw_token, row["token_salt"])
            # Compare hashes in constant time.
            if hmac.compare_digest(candidate, row["token_hash"]):
                # Return the matching seat metadata only.
                return row
        # Do not reveal whether a seat ID existed.
        return None

    def list_seats(self) -> list[sqlite3.Row]:
        """Return public seat metadata plus the reserved operator identity."""

        # Read only non-secret seat fields.
        rows = self.connection.execute(
            "SELECT id, display_name, role, revoked FROM seats ORDER BY id"
        ).fetchall()
        # Add operator as a virtual identity rather than a bearer-token seat.
        return [*rows, {"id": "operator", "display_name": "Founder", "role": "operator"}]

    def known_seats(self) -> set[str]:
        """Return registered agent seat IDs."""

        # Read IDs only because validation does not need credentials.
        rows = self.connection.execute("SELECT id FROM seats WHERE revoked = 0").fetchall()
        # Convert rows into the domain set used by validation.
        return {row["id"] for row in rows}

    def send(self, sender_id: str, message: MessageInput) -> list[dict[str, str | int]]:
        """Persist one message and every delivery in one transaction."""

        # Create one shared message ID.
        message_id = str(uuid4())
        # Create one UTC timestamp shared by all deliveries.
        created_at = _utc_now()
        # Deduplicate recipients before creating delivery records.
        recipients = tuple(dict.fromkeys(message.recipients))
        # Write the message and deliveries atomically.
        with self.transaction() as connection:
            # Insert the shared message record first.
            connection.execute(
                """
                INSERT INTO messages
                    (id, sender_id, ref_url, ref_title, description, kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    sender_id,
                    message.reference.url,
                    message.reference.title,
                    message.description,
                    message.kind,
                    created_at,
                ),
            )
            # Prepare a result for the caller without exposing credentials.
            deliveries: list[dict[str, str | int]] = []
            # Create one independent delivery per recipient.
            for recipient_id in recipients:
                # Load the recipient's next ordered SSE sequence.
                sequence = self._next_sequence(connection, recipient_id)
                # Generate a stable recipient-specific delivery ID.
                delivery_id = str(uuid4())
                # Insert the unread delivery record.
                connection.execute(
                    """
                    INSERT INTO deliveries
                        (id, message_id, recipient_id, sequence, state, created_at)
                    VALUES (?, ?, ?, ?, 'unread', ?)
                    """,
                    (delivery_id, message_id, recipient_id, sequence, created_at),
                )
                # Return the identifiers needed by the service layer.
                deliveries.append(
                    {
                        "message_id": message_id,
                        "delivery_id": delivery_id,
                        "recipient_id": recipient_id,
                        "sequence": sequence,
                    }
                )
        # Return only after the whole transaction commits.
        return deliveries

    def _next_sequence(self, connection: sqlite3.Connection, recipient_id: str) -> int:
        """Allocate the next per-recipient SSE sequence inside a transaction."""

        # Read the current sequence counter for this recipient.
        row = connection.execute(
            "SELECT next_sequence FROM recipient_sequences WHERE recipient_id = ?",
            (recipient_id,),
        ).fetchone()
        # Start sequences at one for a new recipient.
        sequence = 1 if row is None else int(row["next_sequence"])
        # Write the next value for the following delivery.
        connection.execute(
            """
            INSERT INTO recipient_sequences (recipient_id, next_sequence)
            VALUES (?, ?)
            ON CONFLICT(recipient_id) DO UPDATE SET next_sequence = excluded.next_sequence
            """,
            (recipient_id, sequence + 1),
        )
        # Return the sequence assigned to this delivery.
        return sequence

    def inbox(self, recipient_id: str, unread_only: bool) -> list[sqlite3.Row]:
        """Return a recipient's messages in sequence order."""

        # Select either all messages or only unread deliveries.
        query = """
            SELECT
                d.id AS delivery_id,
                d.sequence,
                d.state,
                d.recipient_id,
                m.id AS message_id,
                m.sender_id,
                m.ref_url,
                m.ref_title,
                m.description,
                m.kind,
                m.created_at
            FROM deliveries AS d
            JOIN messages AS m ON m.id = d.message_id
            WHERE d.recipient_id = ?
        """
        # Add the unread filter only when requested.
        if unread_only:
            query += " AND d.state = 'unread'"
        # Keep response ordering stable for polling clients.
        query += " ORDER BY d.sequence"
        # Execute the query with the authenticated recipient ID.
        return self.connection.execute(query, (recipient_id,)).fetchall()

    def acknowledge(self, recipient_id: str, delivery_id: str) -> bool:
        """Mark one delivery read for its authenticated recipient."""

        # Update only the delivery owned by this recipient.
        with self.transaction() as connection:
            # Set read idempotently so repeated acknowledgements are harmless.
            result = connection.execute(
                """
                UPDATE deliveries
                SET state = 'read'
                WHERE id = ? AND recipient_id = ? AND state = 'unread'
                """,
                (delivery_id, recipient_id),
            )
            # Return whether this call changed an unread delivery.
            return result.rowcount == 1

    def stream_after(self, recipient_id: str, sequence: int) -> list[sqlite3.Row]:
        """Return deliveries after a recipient's SSE sequence."""

        # Query only this recipient's ordered events.
        return self.connection.execute(
            """
            SELECT
                d.id AS delivery_id,
                d.sequence,
                d.state,
                d.recipient_id,
                m.id AS message_id,
                m.sender_id,
                m.ref_url,
                m.ref_title,
                m.description,
                m.kind,
                m.created_at
            FROM deliveries AS d
            JOIN messages AS m ON m.id = d.message_id
            WHERE d.recipient_id = ? AND d.sequence > ?
            ORDER BY d.sequence
            """,
            (recipient_id, sequence),
        ).fetchall()


def _hash_token(raw_token: str, salt: bytes) -> bytes:
    """Hash one bearer token with a salt using scrypt."""

    # Derive a memory-hard digest suitable for stored bearer credentials.
    return hashlib.scrypt(
        raw_token.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


def _utc_now() -> str:
    """Return the current time as UTC ISO 8601 text."""

    # Use an explicit UTC offset rather than local machine time.
    return datetime.now(timezone.utc).isoformat()
