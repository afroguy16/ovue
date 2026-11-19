"""Check explicit finite configuration and local versus hosted listener rules."""

from pathlib import Path

import pytest

from ovue.configuration import ConfigurationError, load_settings


def write_config(tmp_path: Path, *, host: str = "127.0.0.1") -> Path:
    """Write a valid test configuration with explicit operational estimates."""
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
max_http_workers = 160
request_timeout_seconds = 10
[server]
host = "{host}"
""",
        encoding="utf-8",
    )
    return config


def test_load_settings_uses_the_configured_data_directory(tmp_path: Path) -> None:
    """Resolve the default protected data directory and explicit limits."""
    settings = load_settings(write_config(tmp_path))

    assert settings.local_deployment
    assert settings.allowed_hosts == frozenset({"work.example.org"})
    assert settings.database_path.name == "ovue.sqlite3"
    assert settings.max_pointer_records == 1000
    assert settings.max_logical_database_bytes == 10_485_760
    assert settings.max_http_workers == 160
    assert settings.request_timeout_seconds == 10


def test_load_settings_requires_worker_capacity_beyond_stream_capacity(
    tmp_path: Path,
) -> None:
    """Reserve at least one HTTP worker for requests outside long-lived streams."""
    config = write_config(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "max_http_workers = 160", "max_http_workers = 128"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="must exceed"):
        load_settings(config)


def test_load_settings_requires_storage_and_retention_estimates(tmp_path: Path) -> None:
    """Refuse to start when a required finite value is missing."""
    config = write_config(tmp_path)
    config.write_text(
        "[reference]\nallowed_hosts=[]\n[storage]\n[retention]\n[limits]\nmax_unread_global=10\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="positive integer"):
        load_settings(config)


def test_example_config_requires_confirmation_before_startup() -> None:
    """Prevent proposed storage and retention estimates from being used silently."""
    example = Path(__file__).parents[1] / "ovue.example.toml"

    with pytest.raises(ConfigurationError, match="positive integer"):
        load_settings(example)


def test_non_local_listener_requires_tls_files(tmp_path: Path) -> None:
    """Reject a public listener unless both TLS files are configured."""
    config = write_config(tmp_path, host="0.0.0.0")

    with pytest.raises(ConfigurationError, match="require TLS"):
        load_settings(config)
