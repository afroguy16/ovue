"""Check optional browser launch stays inside the configured local listener."""

import io
import sys
import threading
import webbrowser
from pathlib import Path
from types import SimpleNamespace

import pytest

from ovue.configuration import ConfigurationError, Settings
from ovue.transports.http import server
from ovue.transports.http.operator_access import OperatorAccess


def make_settings(host: str) -> Settings:
    """Build bounded settings for a local or public listener address."""
    return Settings(
        allowed_hosts=frozenset(),
        data_dir=Path("/tmp/ovue-test"),
        host=host,
        port=8765,
        max_pointer_records=100,
        max_logical_database_bytes=10_000_000,
        pointer_age_days=30,
        log_age_days=90,
        max_unread_global=100,
        tls_certfile=None,
        tls_keyfile=None,
        local_profile=host == "127.0.0.1",
    )


def test_open_local_browser_uses_the_bound_loopback_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open the browser at the actual local port after the server binds."""
    opened: list[tuple[str, int]] = []

    def capture_url(url: str, *, new: int) -> bool:
        opened.append((url, new))
        return True

    monkeypatch.setattr(webbrowser, "open", capture_url)

    url = server.open_local_browser(make_settings("127.0.0.1"), ("127.0.0.1", 9123))

    assert url == "http://127.0.0.1:9123/"
    assert opened == [(url, 2)]


def test_open_local_browser_prints_url_when_no_browser_opens(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep server startup usable when the operating system has no browser."""
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: False)

    url = server.open_local_browser(make_settings("127.0.0.1"), ("127.0.0.1", 9123))

    assert url == "http://127.0.0.1:9123/"
    assert url in capsys.readouterr().out


def test_open_local_browser_rejects_public_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not open the token entry page for a service exposed beyond loopback."""
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: True)

    with pytest.raises(ConfigurationError, match="requires a loopback local profile"):
        server.open_local_browser(make_settings("0.0.0.0"), ("0.0.0.0", 8765))


def test_open_local_browser_rejects_unmarked_loopback_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the generated local-profile marker even for loopback addresses."""
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: True)

    with pytest.raises(ConfigurationError, match="requires a loopback local profile"):
        server.open_local_browser(make_settings("localhost"), ("127.0.0.1", 8765))


def test_operator_browser_requires_an_operator_controlled_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not print the one-time operator code into a redirected output stream."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    with pytest.raises(ConfigurationError, match="operator-controlled terminal"):
        server.serve(make_settings("127.0.0.1"), open_browser=True)


def test_operator_browser_prints_a_one_time_code_before_opening_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Give the local operator a one-time code without putting it in the URL."""

    class Terminal(io.StringIO):
        """Capture terminal output while reporting an interactive terminal."""

        def isatty(self) -> bool:
            """Tell startup that captured output is operator-controlled."""
            return True

    output = Terminal()
    captured: dict[str, OperatorAccess] = {}
    fake_server = SimpleNamespace(
        application=SimpleNamespace(
            stopping=threading.Event(),
            pointers=SimpleNamespace(close=lambda: None),
            seats=SimpleNamespace(close=lambda: None),
        ),
        server_address=("127.0.0.1", 8765),
        serve_forever=lambda **_kwargs: None,
        server_close=lambda: None,
    )

    def capture_server(
        _settings: Settings,
        *,
        operator_access: OperatorAccess | None,
    ) -> SimpleNamespace:
        """Retain the access manager passed to the configured server."""
        assert operator_access is not None
        captured["access"] = operator_access
        return fake_server

    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(server, "create_server", capture_server)
    monkeypatch.setattr(server, "open_local_browser", lambda *_args: "opened")

    server.serve(make_settings("127.0.0.1"), open_browser=True)

    access = captured["access"]
    code = output.getvalue().split(": ", 1)[1].strip()
    assert access.exchange(code) is not None
    assert "127.0.0.1:8765" not in code
