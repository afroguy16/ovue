"""Handle operator send, inbox, and acknowledgement commands."""

from __future__ import annotations

import argparse
import json
from typing import TextIO

from ovue.cli.context import Stores
from ovue.operations.main import (
    Sender,
    acknowledge,
    get_inbox,
    send,
    warn_if_near_capacity,
)
from ovue.operations.validation import Payload, Policy
from ovue.seats.main import known_seat_ids


def send_as_operator(args: argparse.Namespace, stores: Stores, output: TextIO) -> None:
    """Send one pointer as the operator through the standard send operation."""
    result = send(
        Payload(
            tuple(args.recipients),
            args.ref_url,
            args.title,
            args.description,
            args.kind,
        ),
        sender=Sender("operator", "Operator", "operator"),
        known_seat_ids=known_seat_ids(stores.seats),
        policy=Policy(
            allowed_hosts=stores.settings.allowed_hosts,
            max_pointer_records=stores.settings.max_pointer_records,
            max_logical_database_bytes=stores.settings.max_logical_database_bytes,
            max_unread_per_seat=stores.settings.max_unread_per_seat,
            local_deployment=stores.settings.local_deployment,
            max_unread_global=stores.settings.max_unread_global,
        ),
        storage=stores.pointers,
    )
    warn_if_near_capacity(
        stores.pointers,
        max_pointer_records=stores.settings.max_pointer_records,
        max_logical_database_bytes=stores.settings.max_logical_database_bytes,
    )
    print(
        json.dumps(
            {
                "pointer_id": result.pointer_id,
                "deliveries": [
                    {
                        "delivery_id": item.delivery_id,
                        "recipient_id": item.recipient_id,
                        "state": item.state,
                    }
                    for item in result.deliveries
                ],
            }
        ),
        file=output,
    )


def operator_inbox(args: argparse.Namespace, stores: Stores, output: TextIO) -> None:
    """Read the reserved operator inbox with the standard pagination contract."""
    page = get_inbox(
        stores.pointers,
        "operator",
        unread=None if args.unread is None else args.unread == "1",
        limit=args.limit,
        cursor=args.cursor,
    )
    print(
        json.dumps({"items": page.items, "next_cursor": page.next_cursor}), file=output
    )


def acknowledge_operator(
    args: argparse.Namespace, stores: Stores, output: TextIO
) -> None:
    """Acknowledge one delivery addressed to the operator identity."""
    acknowledge(stores.pointers, args.delivery_id, recipient_id="operator")
    print(json.dumps({"delivery_id": args.delivery_id, "state": "read"}), file=output)
