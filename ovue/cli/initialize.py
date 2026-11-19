"""Create a private, loopback-only configuration for local Ovue use."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from ovue.configuration import ConfigurationError, normalize_allowed_hosts

_LOCAL_LIMITS = {
    "max_pointer_records": 100_000,
    "max_logical_database_bytes": 268_435_456,
    "acknowledged_pointer_max_age_days": 30,
    "traffic_log_max_age_days": 90,
    "max_unread_global": 1_000,
}


def initialize_local(config_path: Path, allow_hosts: Sequence[str]) -> Path:
    """Create a secure local configuration without replacing an existing file."""
    allowed_hosts = normalize_allowed_hosts(allow_hosts)
    config_text = _local_configuration(allowed_hosts)
    try:
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise ConfigurationError(
            "Could not create the configuration directory"
        ) from None

    try:
        descriptor = os.open(
            config_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        raise ConfigurationError("Configuration file already exists") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as config_file:
            config_file.write(config_text)
            config_file.flush()
            os.fsync(config_file.fileno())
    except OSError:
        try:
            config_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConfigurationError("Could not write the local configuration") from None
    return config_path


def _local_configuration(allowed_hosts: frozenset[str]) -> str:
    """Render every required finite value and the local-profile marker as TOML."""
    hosts = ", ".join(json.dumps(host) for host in sorted(allowed_hosts))
    return f"""[reference]
allowed_hosts = [{hosts}]

[storage]
max_pointer_records = {_LOCAL_LIMITS["max_pointer_records"]}
max_logical_database_bytes = {_LOCAL_LIMITS["max_logical_database_bytes"]}

[retention]
acknowledged_pointer_max_age_days = {_LOCAL_LIMITS["acknowledged_pointer_max_age_days"]}
traffic_log_max_age_days = {_LOCAL_LIMITS["traffic_log_max_age_days"]}

[limits]
max_unread_global = {_LOCAL_LIMITS["max_unread_global"]}

[server]
data_dir = "~/.local/share/ovue"
host = "127.0.0.1"
port = 8765

[local]
profile = true
"""
