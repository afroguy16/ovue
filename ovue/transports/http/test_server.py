"""Check optional browser launch stays inside the configured local listener."""

import webbrowser
from pathlib import Path

import pytest

from ovue.configuration import ConfigurationError, Settings
from ovue.transports.http import server


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
