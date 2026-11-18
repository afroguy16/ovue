"""Check the public command tree and one-time token output rules."""

from __future__ import annotations

import io
import json
from importlib import import_module
from pathlib import Path

import pytest

from ovue.cli.main import main
from ovue.cli.parser import build_parser
from ovue.configuration import Settings
from ovue.operations.main import Sender, send
from ovue.operations.validation import Payload, Policy
from ovue.storage.main import SQLite
from ovue.storage.seats import SeatStorage


class TerminalCapture(io.StringIO):
    """Capture command output while declaring it is a controlled terminal."""

    def isatty(self) -> bool:
        """Tell CLI token actions that this output is an operator terminal."""
        return True


def make_config(tmp_path: Path) -> Path:
    """Write a working local configuration for CLI command tests."""
    config = tmp_path / "ovue.toml"
    config.write_text(
        f"""
[reference]
allowed_hosts = ["work.example.org"]
[storage]
max_pointer_records = 1000
max_logical_database_bytes = 10485760
[retention]
acknowledged_pointer_max_age_days = 30
traffic_log_max_age_days = 90
[limits]
max_unread_global = 1000
[server]
data_dir = "{tmp_path / "data"}"
""",
        encoding="utf-8",
    )
    return config


def test_parser_requires_a_known_command() -> None:
    """Show every supported local action from the root help output."""
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["--help"])
    assert error.value.code == 0


def test_serve_command_loads_configuration_before_starting_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass validated operator settings to the HTTP server without opening stores."""
    config = make_config(tmp_path)
    started_with: list[Settings] = []

    def capture_settings(settings: Settings) -> None:
        started_with.append(settings)

    cli_module = import_module("ovue.cli.main")
    monkeypatch.setattr(cli_module, "serve", capture_settings)

    main(["--config", str(config), "serve"])

    assert len(started_with) == 1
    assert started_with[0].data_dir == tmp_path / "data"
    assert started_with[0].allowed_hosts == frozenset({"work.example.org"})


def test_serve_does_not_start_when_required_configuration_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop before server startup when required finite settings are absent."""
    config = tmp_path / "incomplete.toml"
    config.write_text(
        """
[reference]
allowed_hosts = []
[storage]
max_logical_database_bytes = 10485760
[retention]
acknowledged_pointer_max_age_days = 30
traffic_log_max_age_days = 90
[limits]
max_unread_global = 1000
""",
        encoding="utf-8",
    )
    started_with: list[Settings] = []

    def capture_settings(settings: Settings) -> None:
        """Record an unexpected server start so the test can reject it."""
        started_with.append(settings)

    cli_module = import_module("ovue.cli.main")
    monkeypatch.setattr(cli_module, "serve", capture_settings)
    errors = io.StringIO()

    with pytest.raises(SystemExit) as result:
        main(["--config", str(config), "serve"], errors=errors)

    assert result.value.code == 2
    assert "max_pointer_records" in errors.getvalue()
    assert started_with == []


def test_seat_creation_refuses_to_emit_a_token_to_non_terminal_output(
    tmp_path: Path,
) -> None:
    """Avoid issuing a credential when the CLI cannot safely show it once."""
    config = make_config(tmp_path)
    output = io.StringIO()
    errors = io.StringIO()

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--config",
                str(config),
                "seat",
                "create",
                "--handle",
                "writer",
                "--display-name",
                "Ese",
                "--role",
                "Writer",
            ],
            output=output,
            errors=errors,
        )

    assert error.value.code == 2
    assert "requires an operator-controlled terminal" in errors.getvalue()
    assert output.getvalue() == ""
    store = SeatStorage(
        tmp_path / "data" / "ovue.sqlite3", max_logical_database_bytes=10_000_000
    )
    assert store.list_seats() == ()
    store.close()


def test_cli_creates_lists_and_rotates_a_seat_token_once(tmp_path: Path) -> None:
    """Expose seat management actions while keeping tokens out of the directory."""
    config = make_config(tmp_path)
    output = TerminalCapture()
    main(
        [
            "--config",
            str(config),
            "seat",
            "create",
            "--handle",
            "writer",
            "--display-name",
            "Ese",
            "--role",
            "Writer",
        ],
        output=output,
    )
    created = json.loads(output.getvalue())
    seat_id = created["id"]
    old_token = created["token"]

    listed = io.StringIO()
    main(["--config", str(config), "seat", "list"], output=listed)
    assert old_token not in listed.getvalue()

    rotated = TerminalCapture()
    main(
        ["--config", str(config), "token", "rotate", seat_id],
        output=rotated,
    )
    new_token = rotated.getvalue().split(": ", maxsplit=1)[1].strip()
    store = SeatStorage(
        tmp_path / "data" / "ovue.sqlite3", max_logical_database_bytes=10_000_000
    )
    assert store.authenticate(new_token).id == seat_id
    with pytest.raises(PermissionError):
        store.authenticate(old_token)
    store.close()


def test_operator_commands_send_read_acknowledge_log_and_purge(
    tmp_path: Path,
) -> None:
    """Exercise operator pointer actions through the local command surface."""
    config = make_config(tmp_path)
    created_output = TerminalCapture()
    main(
        [
            "--config",
            str(config),
            "seat",
            "create",
            "--handle",
            "writer",
            "--display-name",
            "Ese",
            "--role",
            "Writer",
        ],
        output=created_output,
    )
    seat_data = json.loads(created_output.getvalue())
    seat_id = seat_data["id"]

    founder_send = io.StringIO()
    main(
        [
            "--config",
            str(config),
            "send",
            "--to",
            seat_id,
            "--ref-url",
            "https://work.example.org/items/42",
            "--title",
            "CT-2",
            "--description",
            "Ready",
            "--kind",
            "done",
        ],
        output=founder_send,
    )
    assert (
        json.loads(founder_send.getvalue())["deliveries"][0]["recipient_id"] == seat_id
    )

    seats = SeatStorage(
        tmp_path / "data" / "ovue.sqlite3", max_logical_database_bytes=10_000_000
    )
    sender = seats.authenticate(seat_data["token"])
    pointers = SQLite(
        tmp_path / "data" / "ovue.sqlite3", max_logical_database_bytes=10_000_000
    )
    send(
        Payload(
            ("operator",),
            "https://work.example.org/items/43",
            None,
            "Needs Founder decision",
            "needs-decision",
        ),
        sender=Sender(sender.id, sender.display_name, sender.role),
        known_seat_ids={seat_id},
        policy=Policy(frozenset({"work.example.org"}), 1000, 10_485_760, 100),
        storage=pointers,
    )
    pointers.close()
    seats.close()

    inbox_output = io.StringIO()
    main(["--config", str(config), "inbox", "--unread", "1"], output=inbox_output)
    inbox = json.loads(inbox_output.getvalue())
    delivery_id = inbox["items"][0]["delivery_id"]
    assert inbox["items"][0]["from"]["id"] == seat_id

    acknowledged = io.StringIO()
    main(
        ["--config", str(config), "ack", delivery_id],
        output=acknowledged,
    )
    assert json.loads(acknowledged.getvalue())["state"] == "read"

    traffic = io.StringIO()
    main(["--config", str(config), "traffic"], output=traffic)
    assert json.loads(traffic.getvalue().splitlines()[0])["state"] in {"unread", "read"}

    purged = io.StringIO()
    main(["--config", str(config), "purge"], output=purged)
    assert "Deleted" in purged.getvalue()


def test_cli_reports_invalid_operator_send_as_safe_json(tmp_path: Path) -> None:
    """Report pointer validation issues without a traceback or submitted values."""
    config = make_config(tmp_path)
    errors = io.StringIO()

    with pytest.raises(SystemExit) as result:
        main(
            [
                "--config",
                str(config),
                "send",
                "--to",
                "unknown-seat",
                "--ref-url",
                "https://work.example.org/items/42",
                "--description",
                "Private text",
                "--kind",
                "done",
            ],
            errors=errors,
        )

    error = json.loads(errors.getvalue())
    assert result.value.code == 2
    assert error["error"] == "validation_failed"
    assert error["issues"][0]["code"] == "unknown_seat_id"
    assert "unknown-seat" not in errors.getvalue()
    assert "Private text" not in errors.getvalue()
