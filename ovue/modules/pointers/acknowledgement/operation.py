"""Acknowledge one delivery for the authenticated recipient."""

from ovue.modules.pointers.storage.sqlite import SQLite


def acknowledge(storage: SQLite, delivery_id: str, *, recipient_id: str) -> None:
    """Mark the recipient's delivery read, or hide a foreign ID as not found."""
    storage.acknowledge_delivery(delivery_id, recipient_id)
