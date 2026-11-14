"""Load the operator's explicit finite limits and local service settings."""

from __future__ import annotations

import ipaddress
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Report a safe configuration problem without exposing file contents."""


_HOSTNAME_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\."
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\Z"
)


@dataclass(frozen=True)
class Settings:
    """Hold validated service, storage, retention, and capacity settings."""

    allowed_hosts: frozenset[str]
    data_dir: Path
    host: str
    port: int
    max_pointer_records: int
    max_logical_database_bytes: int
    pointer_age_days: int
    log_age_days: int
    max_unread_global: int
    tls_certfile: Path | None
    tls_keyfile: Path | None
    send_per_minute: int = 60
    invalid_per_minute: int = 60
    max_body_bytes: int = 4096
    max_streams_per_seat: int = 8
    max_streams_global: int = 128
    max_unread_per_seat: int = 100
    max_replay_events: int = 1000
    max_http_workers: int = 160
    request_timeout_seconds: int = 10

    @property
    def database_path(self) -> Path:
        """Return the SQLite file inside the protected data directory."""
        return self.data_dir / "ovue.sqlite3"

    @property
    def local_deployment(self) -> bool:
        """Return whether the configured listener binds only to loopback."""
        if self.host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return False


def load_settings(config_path: Path) -> Settings:
    """Load TOML settings and require finite storage and retention values."""
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise ConfigurationError("Configuration file cannot be read") from None
    if not isinstance(raw, dict):
        raise ConfigurationError("Configuration root must be a table")

    reference = _table(raw, "reference")
    storage = _table(raw, "storage")
    retention = _table(raw, "retention")
    server = _table(raw, "server", optional=True)
    limits = _table(raw, "limits", optional=True)

    allowed_hosts_raw = reference.get("allowed_hosts", [])
    if not isinstance(allowed_hosts_raw, list) or not all(
        isinstance(host, str) and host for host in allowed_hosts_raw
    ):
        raise ConfigurationError("reference.allowed_hosts must be a list of hostnames")
    allowed_hosts = frozenset(host.lower() for host in allowed_hosts_raw)
    if any(not _is_allowed_hostname(host) for host in allowed_hosts):
        raise ConfigurationError(
            "reference.allowed_hosts entries must be exact ASCII hostnames"
        )

    data_dir_value = server.get("data_dir", "~/.local/share/ovue")
    if not isinstance(data_dir_value, str) or not data_dir_value:
        raise ConfigurationError("server.data_dir must be a path")
    data_dir = Path(data_dir_value).expanduser().resolve()
    host = _string(server.get("host", "127.0.0.1"), "server.host")
    port = _positive_int(server.get("port", 8765), "server.port")
    if port > 65535:
        raise ConfigurationError("server.port must be at most 65535")

    certfile = _optional_path(server.get("tls_certfile"), "server.tls_certfile")
    keyfile = _optional_path(server.get("tls_keyfile"), "server.tls_keyfile")
    max_streams_global = _positive_int(
        limits.get("max_streams_global", 128), "limits.max_streams_global"
    )
    settings = Settings(
        allowed_hosts=allowed_hosts,
        data_dir=data_dir,
        host=host,
        port=port,
        max_pointer_records=_positive_int(
            storage.get("max_pointer_records"), "storage.max_pointer_records"
        ),
        max_logical_database_bytes=_positive_int(
            storage.get("max_logical_database_bytes"),
            "storage.max_logical_database_bytes",
        ),
        pointer_age_days=_positive_int(
            retention.get("acknowledged_pointer_max_age_days"),
            "retention.acknowledged_pointer_max_age_days",
        ),
        log_age_days=_positive_int(
            retention.get("traffic_log_max_age_days"),
            "retention.traffic_log_max_age_days",
        ),
        max_unread_global=_positive_int(
            limits.get("max_unread_global"), "limits.max_unread_global"
        ),
        tls_certfile=certfile,
        tls_keyfile=keyfile,
        send_per_minute=_positive_int(
            limits.get("send_per_minute", 60), "limits.send_per_minute"
        ),
        invalid_per_minute=_positive_int(
            limits.get("invalid_per_minute", 60), "limits.invalid_per_minute"
        ),
        max_body_bytes=_positive_int(
            limits.get("max_body_bytes", 4096), "limits.max_body_bytes"
        ),
        max_streams_per_seat=_positive_int(
            limits.get("max_streams_per_seat", 8),
            "limits.max_streams_per_seat",
        ),
        max_streams_global=max_streams_global,
        max_unread_per_seat=_positive_int(
            limits.get("max_unread_per_seat", 100),
            "limits.max_unread_per_seat",
        ),
        max_replay_events=_positive_int(
            limits.get("max_replay_events", 1000), "limits.max_replay_events"
        ),
        max_http_workers=_positive_int(
            limits.get("max_http_workers", max_streams_global + 32),
            "limits.max_http_workers",
        ),
        request_timeout_seconds=_positive_int(
            limits.get("request_timeout_seconds", 10),
            "limits.request_timeout_seconds",
        ),
    )
    if settings.max_body_bytes > 4096:
        raise ConfigurationError("limits.max_body_bytes cannot exceed 4096")
    if settings.max_unread_per_seat < 10:
        raise ConfigurationError(
            "limits.max_unread_per_seat must reserve ten deliveries"
        )
    if settings.max_http_workers <= settings.max_streams_global:
        raise ConfigurationError(
            "limits.max_http_workers must exceed limits.max_streams_global"
        )
    if not settings.local_deployment and (certfile is None or keyfile is None):
        raise ConfigurationError("Non-local listeners require TLS certificate and key")
    if certfile is not None and not certfile.is_file():
        raise ConfigurationError("TLS certificate file does not exist")
    if keyfile is not None and not keyfile.is_file():
        raise ConfigurationError("TLS private-key file does not exist")
    return settings


def _table(raw: dict[str, Any], key: str, *, optional: bool = False) -> dict[str, Any]:
    """Return one TOML table and reject a missing required or malformed table."""
    value = raw.get(key, {} if optional else None)
    if not isinstance(value, dict):
        raise ConfigurationError(f"[{key}] must be a table")
    return value


def _positive_int(value: object, name: str) -> int:
    """Require a positive integer without accepting booleans or estimates as text."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(f"{name} must be an explicit positive integer")
    return value


def _string(value: object, name: str) -> str:
    """Require a non-empty string for a configured text field."""
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value


def _optional_path(value: object, name: str) -> Path | None:
    """Expand an optional filesystem path from the configuration file."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{name} must be a path")
    return Path(value).expanduser().resolve()


def _is_allowed_hostname(value: str) -> bool:
    """Reject wildcards, IP literals, trailing dots, and non-DNS host values."""
    if not value.isascii() or "xn--" in value or not _HOSTNAME_PATTERN.fullmatch(value):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return True
    return False
