"""Connect parsed operator commands to Ovue module operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from ovue.cli import maintenance, pointer, seat, token
from ovue.cli.context import open_stores
from ovue.cli.parser import build_parser
from ovue.configuration import ConfigurationError, load_settings
from ovue.modules.pointers.validation.validation import IssueRejected
from ovue.transports.http.server import serve


def main(
    argv: Sequence[str] | None = None,
    *,
    output: TextIO | None = None,
    errors: TextIO | None = None,
) -> None:
    """Run one Ovue command and report safe operator-facing errors."""
    stdout = output or sys.stdout
    stderr = errors or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _dispatch(args, stdout)
    except IssueRejected as error:
        print(
            json.dumps(
                {
                    "error": "validation_failed",
                    "issues": [
                        {
                            "path": list(issue.path),
                            "code": issue.code,
                            "message": issue.message,
                            **(
                                {"max": issue.max_value}
                                if issue.max_value is not None
                                else {}
                            ),
                        }
                        for issue in error.issues
                    ],
                }
            ),
            file=stderr,
        )
        raise SystemExit(2) from None
    except (ConfigurationError, KeyError, PermissionError, ValueError) as error:
        print(str(error), file=stderr)
        raise SystemExit(2) from None


def _dispatch(args: argparse.Namespace, output: TextIO) -> None:
    """Open only the resources required by the requested operator action."""
    config_path: Path = args.config
    if args.command == "serve":
        serve(load_settings(config_path))
        return
    with open_stores(config_path) as stores:
        if args.command == "seat":
            if args.seat_command == "create":
                seat.create(args, stores, output)
            elif args.seat_command == "list":
                seat.list_seats(stores, output)
            else:
                seat.rename(args, stores, output)
        elif args.command == "token":
            if args.token_command == "revoke":
                token.revoke(args, stores, output)
            else:
                token.rotate(args, stores, output)
        elif args.command == "send":
            pointer.send_as_operator(args, stores, output)
        elif args.command == "inbox":
            pointer.operator_inbox(args, stores, output)
        elif args.command == "ack":
            pointer.acknowledge_operator(args, stores, output)
        elif args.command == "traffic":
            maintenance.traffic(stores, output, limit=args.limit)
        elif args.command == "purge":
            maintenance.purge_history(stores, output, vacuum=args.vacuum)
        else:
            raise ValueError("Unknown Ovue command")
