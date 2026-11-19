"""Expose the pointer operations used by Ovue's entry points."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import cast
from weakref import WeakKeyDictionary

from ovue.operations.utils import decode_cursor, encode_cursor
from ovue.operations.validation import Issue, IssueRejected, Payload, Policy, validate
from ovue.storage.main import (
    CapacityReached,
    PointerRecord,
    PointerStorage,
)


@dataclass(frozen=True)
class Sender:
    """Identify the authenticated seat that is submitting the pointer."""

    id: str
    display_name: str
    role: str


@dataclass(frozen=True)
class Delivery:
    """Describe one recipient delivery returned by a pointer operation."""

    delivery_id: str
    recipient_id: str
    state: str


@dataclass(frozen=True)
class SendResult:
    """Return the created pointer ID and its recipient deliveries."""

    pointer_id: str
    deliveries: tuple[Delivery, ...]


def send(
    payload: Payload,
    *,
    sender: Sender,
    known_seat_ids: set[str],
    policy: Policy,
    storage: PointerStorage,
) -> SendResult:
    """Validate the payload, persist it atomically, and return its IDs."""
    recipients = validate(
        payload,
        sender_id=sender.id,
        known_seat_ids=known_seat_ids,
        policy=policy,
    )
    pointer = PointerRecord(
        sender_id=sender.id,
        sender_display_name=sender.display_name,
        sender_role=sender.role,
        recipients=recipients,
        ref_url=payload.ref_url,
        ref_title=payload.ref_title,
        description=payload.description,
        kind=payload.kind,
    )
    try:
        pointer_id, deliveries = storage.persist_send(
            pointer,
            max_pointer_records=policy.max_pointer_records,
            max_logical_database_bytes=policy.max_logical_database_bytes,
            max_unread_per_seat=policy.max_unread_per_seat,
            max_unread_global=policy.max_unread_global,
        )
    except CapacityReached as error:
        # Translate storage capacity into the same issue shape as input rejection.
        raise IssueRejected(
            (
                Issue(
                    error.code,
                    error.message,
                    error.path,
                    error.max_value,
                ),
            )
        ) from None
    return SendResult(
        pointer_id=pointer_id,
        deliveries=tuple(
            Delivery(
                delivery_id=delivery.delivery_id,
                recipient_id=delivery.recipient_id,
                state=delivery.state,
            )
            for delivery in deliveries
        ),
    )


@dataclass(frozen=True)
class InboxPage:
    """Hold one inbox page and its optional continuation cursor."""

    items: tuple[dict[str, object], ...]
    next_cursor: str | None


def get_inbox(
    storage: PointerStorage,
    seat_id: str,
    *,
    unread: bool | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> InboxPage:
    """Return a filtered inbox page without exposing cursor internals to clients."""
    if not 1 <= limit <= 100:
        raise ValueError("Inbox limit must be between 1 and 100")
    after_sequence = decode_cursor(cursor) if cursor is not None else 0
    if after_sequence > storage.latest_sequence(seat_id):
        raise ValueError("Inbox cursor is invalid")
    rows = storage.get_inbox(
        seat_id,
        unread=unread,
        after_sequence=after_sequence,
        limit=limit + 1,
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(cast(int, items[-1]["event_id"])) if has_more else None
    return InboxPage(items, next_cursor)


def acknowledge(
    storage: PointerStorage,
    delivery_id: str,
    *,
    recipient_id: str,
) -> None:
    """Mark the recipient's delivery read, or hide a foreign ID as not found."""
    storage.acknowledge_delivery(delivery_id, recipient_id)


def replay_after(
    storage: PointerStorage,
    seat_id: str,
    last_event_id: str,
    *,
    limit: int = 1000,
) -> tuple[dict[str, object], ...]:
    """Return events after Last-Event-ID or raise a safe cursor error."""
    if not last_event_id.isascii() or not last_event_id.isdecimal():
        raise ValueError("Event cursor is invalid") from None
    sequence = int(last_event_id)
    if sequence < 0:
        raise ValueError("Event cursor is invalid")
    return storage.replay_after(seat_id, sequence, limit=limit)


def unread_backlog(
    storage: PointerStorage,
    seat_id: str,
) -> tuple[dict[str, object], ...]:
    """Return the bounded unread inbox before a new live stream begins."""
    return storage.get_inbox(seat_id, unread=True, after_sequence=0, limit=101)


@dataclass(frozen=True)
class StreamStart:
    """Hold the events to send first and the next sequence to poll from."""

    events: tuple[dict[str, object], ...]
    next_sequence: int


def start_stream(
    storage: PointerStorage,
    seat_id: str,
    *,
    last_event_id: str | None,
    replay_limit: int = 1000,
    unread_limit: int = 100,
) -> StreamStart:
    """Send unread backlog on a new connection or replay after its last event."""
    if last_event_id is None:
        events, latest = storage.initial_stream_state(seat_id, unread_limit)
        if len(events) > unread_limit:
            raise RuntimeError("Unread backlog exceeds the configured inbox limit")
        return StreamStart(events, latest)
    if not last_event_id.isascii() or not last_event_id.isdecimal():
        raise ValueError("Event cursor is invalid") from None
    sequence = int(last_event_id)
    if sequence < 0:
        raise ValueError("Event cursor is invalid")
    events = storage.replay_after(seat_id, sequence, limit=replay_limit)
    return StreamStart(events, sequence)


def events_after(
    storage: PointerStorage,
    seat_id: str,
    sequence: int,
    *,
    replay_limit: int = 1000,
) -> tuple[dict[str, object], ...]:
    """Return later deliveries for an already-open seat stream."""
    return storage.replay_after(seat_id, sequence, limit=replay_limit)


@dataclass(frozen=True)
class PurgeResult:
    """Report how many pointer rows and traffic rows were removed."""

    pointers_deleted: int
    traffic_rows_deleted: int


def purge(
    storage: PointerStorage,
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


def read_traffic(storage: PointerStorage, *, limit: int = 100) -> tuple[str, ...]:
    """Return recent traffic records as one safely escaped JSON object per line."""
    if not 1 <= limit <= 1000:
        raise ValueError("Traffic history limit must be between 1 and 1000")
    return tuple(
        json.dumps(
            {key: value for key, value in record.items() if key != "_log_id"},
            ensure_ascii=True,
            separators=(",", ":"),
        )
        for record in storage.read_traffic(limit=limit)
    )


_WARNING_STATES: WeakKeyDictionary[
    PointerStorage,
    dict[str, bool],
] = WeakKeyDictionary()

_WARNING_LOCK = threading.Lock()


def warn_if_near_capacity(
    storage: PointerStorage,
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
