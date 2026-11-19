"""Check local configuration creation, host validation, and safe file handling."""

from __future__ import annotations

import io
import stat
import tomllib
from pathlib import Path

import pytest

from ovue.cli.main import main
from ovue.configuration import ConfigurationError, load_settings


def test_init_writes_finite_local_config_with_exact_hosts(tmp_path: Path) -> None:
    """Write a usable loopback config with normalized, duplicate-free hosts."""
    config = tmp_path / "config" / "ovue.toml"
    output = io.StringIO()

    main(
        [
            "--config",
            str(config),
            "init",
            "--local",
            "--allow-host",
            "APP.NOTION.COM",
            "--allow-host",
            "work.example.org",
            "--allow-host",
            "app.notion.com",
        ],
        output=output,
    )

    settings = load_settings(config)
    values = tomllib.loads(config.read_text(encoding="utf-8"))
    assert settings.local_profile
    assert settings.local_deployment
    assert settings.allowed_hosts == frozenset({"app.notion.com", "work.example.org"})
    assert settings.max_pointer_records == 100_000
    assert settings.max_logical_database_bytes == 268_435_456
    assert settings.pointer_age_days == 30
    assert settings.log_age_days == 90
    assert values["server"]["data_dir"] == "~/.local/share/ovue"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert "Next: ovue serve" in output.getvalue()


def test_init_without_allowed_hosts_creates_an_empty_allowlist(
    tmp_path: Path,
) -> None:
    """Leave external reference hosts disabled when no host option is supplied."""
    config = tmp_path / "ovue.toml"

    main(["--config", str(config), "init", "--local"], output=io.StringIO())

    assert load_settings(config).allowed_hosts == frozenset()


@pytest.mark.parametrize(
    "invalid_host",
    (
        "https://work.example.org",
        "*.example.org",
        "192.0.2.1",
        "work.example.org.",
        "work.example.org:8443",
        "work.example.org/path",
        "xn--bcher-kva.example",
    ),
)
def test_init_rejects_invalid_hosts_before_creating_config(
    tmp_path: Path,
    invalid_host: str,
) -> None:
    """Reject schemes and other non-host values without creating the config file."""
    config = tmp_path / "nested" / "ovue.toml"
    errors = io.StringIO()

    with pytest.raises(SystemExit) as result:
        main(
            [
                "--config",
                str(config),
                "init",
                "--local",
                "--allow-host",
                invalid_host,
            ],
            output=io.StringIO(),
            errors=errors,
        )

    assert result.value.code == 2
    assert not config.exists()
    assert invalid_host not in errors.getvalue()


def test_init_does_not_replace_existing_config(tmp_path: Path) -> None:
    """Preserve the existing configuration when initialization is repeated."""
    config = tmp_path / "ovue.toml"
    config.write_text("keep this file", encoding="utf-8")

    with pytest.raises(SystemExit) as result:
        main(["--config", str(config), "init", "--local"], output=io.StringIO())

    assert result.value.code == 2
    assert config.read_text(encoding="utf-8") == "keep this file"


def test_local_profile_rejects_non_loopback_listener(tmp_path: Path) -> None:
    """Prevent a generated local-only profile from being exposed publicly."""
    config = tmp_path / "ovue.toml"
    config.write_text(
        """[reference]
allowed_hosts = []
[storage]
max_pointer_records = 1000
max_logical_database_bytes = 10485760
[retention]
acknowledged_pointer_max_age_days = 30
traffic_log_max_age_days = 90
[limits]
max_unread_global = 1000
[server]
host = "0.0.0.0"
[local]
profile = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="local profile must use a loopback"):
        load_settings(config)
