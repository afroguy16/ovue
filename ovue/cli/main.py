"""Connect parsed operator commands to Ovue module operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from ovue.cli import initialize, maintenance, pointer, seat, token
from ovue.cli.context import open_stores
from ovue.cli.parser import build_parser
from ovue.configuration import ConfigurationError, load_settings
from ovue.operations.validation import IssueRejected
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
    if args.command == "init":
        created_path = initialize.initialize_local(config_path, args.allow_host)
        print(f"Created local configuration: {created_path}", file=output)
        print("Next: ovue serve", file=output)
        return
    if args.command == "serve":
        settings = load_settings(config_path)
        if args.open_browser and (
            not settings.local_profile or not settings.local_deployment
        ):
            raise ConfigurationError(
                "The browser connection check requires a loopback local profile"
            )
        if args.open_browser:
            serve(settings, open_browser=True)
        else:
            serve(settings)
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
