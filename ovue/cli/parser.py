"""Define the operator commands and their explicit inputs."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build the root CLI parser and the seat, token, pointer, and server actions."""
    parser = argparse.ArgumentParser(
        prog="ovue",
        description="Run the Ovue pointer service or manage it locally.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("~/.config/ovue/config.toml").expanduser(),
        help="path to the operator's TOML configuration file",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="start the HTTP and SSE service")

    seats = commands.add_parser("seat", help="manage registered seats")
    seat_commands = seats.add_subparsers(dest="seat_command", required=True)
    create = seat_commands.add_parser(
        "create", help="register a seat and issue a token"
    )
    create.add_argument("--handle", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", required=True)
    seat_commands.add_parser("list", help="list seats and token status")
    rename = seat_commands.add_parser("rename", help="change a seat's handle")
    rename.add_argument("seat_id")
    rename.add_argument("handle")

    tokens = commands.add_parser("token", help="manage seat bearer tokens")
    token_commands = tokens.add_subparsers(dest="token_command", required=True)
    revoke = token_commands.add_parser("revoke", help="invalidate a seat's token")
    revoke.add_argument("seat_id")
    rotate = token_commands.add_parser("rotate", help="replace a seat's token")
    rotate.add_argument("seat_id")

    send = commands.add_parser("send", help="send a pointer as the operator")
    send.add_argument("--to", action="append", required=True, dest="recipients")
    send.add_argument("--ref-url", required=True)
    send.add_argument("--title")
    send.add_argument("--description", required=True)
    send.add_argument(
        "--kind",
        required=True,
        choices=("done", "blocked", "needs-decision", "info", "acknowledged"),
    )

    inbox = commands.add_parser("inbox", help="read the operator's inbox")
    inbox.add_argument("--unread", choices=("0", "1"))
    inbox.add_argument("--limit", type=int, default=50)
    inbox.add_argument("--cursor")

    acknowledge = commands.add_parser("ack", help="acknowledge an operator delivery")
    acknowledge.add_argument("delivery_id")

    traffic = commands.add_parser("traffic", help="read recent pointer traffic")
    traffic.add_argument("--limit", type=int, default=100)

    purge = commands.add_parser("purge", help="remove expired pointers and log rows")
    purge.add_argument("--vacuum", action="store_true", help="shrink the SQLite file")
    return parser
