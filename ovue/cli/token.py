"""Handle local revocation and one-time bearer-token rotation output."""

import argparse
from typing import TextIO

from ovue.cli.context import Stores
from ovue.modules.seats.management.operation import revoke_token, rotate_token


def revoke(args: argparse.Namespace, stores: Stores, output: TextIO) -> None:
    """Revoke the current token without printing or retaining it."""
    revoke_token(stores.seats, args.seat_id)
    print("Token revoked", file=output)


def rotate(args: argparse.Namespace, stores: Stores, output: TextIO) -> None:
    """Replace a token and display the new raw value only in a terminal."""
    if not output.isatty():
        raise ValueError("Token rotation requires an operator-controlled terminal")
    token = rotate_token(stores.seats, args.seat_id)
    print(f"Bearer token (shown once): {token}", file=output)
