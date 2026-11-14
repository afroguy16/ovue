"""Handle local seat creation, listing, and handle changes."""

from __future__ import annotations

import argparse
import json
from typing import TextIO

from ovue.cli.context import Stores
from ovue.modules.seats.management.operation import create_seat, rename_seat


def create(args: argparse.Namespace, stores: Stores, output: TextIO) -> None:
    """Create a seat and show its raw bearer token only on a terminal."""
    if not output.isatty():
        raise ValueError("Seat creation requires an operator-controlled terminal")
    seat, token = create_seat(
        stores.seats,
        stores.settings,
        handle=args.handle,
        display_name=args.display_name,
        role=args.role,
    )
    print(
        json.dumps(
            {
                "id": seat.id,
                "handle": seat.handle,
                "display_name": seat.display_name,
                "role": seat.role,
                "token": token,
            },
            ensure_ascii=True,
        ),
        file=output,
    )


def list_seats(stores: Stores, output: TextIO) -> None:
    """List seat metadata and token status without printing token material."""
    items = [
        {
            "id": seat.id,
            "handle": seat.handle,
            "display_name": seat.display_name,
            "role": seat.role,
            "token_status": "active" if seat.token_active else "revoked",
        }
        for seat in stores.seats.list_seats()
    ]
    print(json.dumps({"items": items}, ensure_ascii=True), file=output)


def rename(args: argparse.Namespace, stores: Stores, output: TextIO) -> None:
    """Rename a seat handle without changing its ID or existing deliveries."""
    seat = rename_seat(stores.seats, args.seat_id, args.handle)
    print(json.dumps({"id": seat.id, "handle": seat.handle}), file=output)
