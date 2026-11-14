"""Coordinate validation and durable persistence for one send operation."""

from __future__ import annotations

from dataclasses import dataclass

from ovue.modules.pointers.storage.sqlite import (
    CapacityReached,
    DeliveredPointer,
    PointerRecord,
    SQLite,
)
from ovue.modules.pointers.validation.validation import (
    Issue,
    IssueRejected,
    Payload,
    Policy,
    validate,
)


@dataclass(frozen=True)
class Sender:
    """Identify the authenticated seat that is submitting the pointer."""

    id: str
    display_name: str
    role: str


@dataclass(frozen=True)
class SendResult:
    """Return the created pointer ID and its recipient deliveries."""

    pointer_id: str
    deliveries: tuple[DeliveredPointer, ...]


def send(
    payload: Payload,
    *,
    sender: Sender,
    known_seat_ids: set[str],
    policy: Policy,
    storage: SQLite,
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
    return SendResult(pointer_id=pointer_id, deliveries=deliveries)
