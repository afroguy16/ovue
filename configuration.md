# Configuration reference

Author: Okoro (AI Agent)
Human Driver: Jonathan

Ovue reads TOML configuration. Finite storage and retention values are required at startup; the values in [`ovue.example.toml`](ovue.example.toml) are proposals and must be confirmed for each deployment.

## Package startup

The installed `ovue` command and `python -m ovue` call the same CLI entry point. Both accept the same options and commands. Put the global `--config` option before the command, for example `ovue --config ~/.config/ovue/config.toml serve`. If omitted, Ovue reads `~/.config/ovue/config.toml`.

Startup loads and validates the configuration before starting the HTTP server or opening stores for an administrative command. Invalid or missing required values stop the command with a safe configuration error.

## Settings

| Table | Setting | Meaning |
| --- | --- | --- |
| `reference` | `allowed_hosts` | Exact hostnames accepted in pointer URLs. The list is empty by default. |
| `server` | `host`, `port` | Listener address. A non-local listener requires `tls_certfile` and `tls_keyfile`. |
| `server` | `data_dir` | Private directory containing the SQLite database. Defaults to `~/.local/share/ovue`. |
| `storage` | `max_pointer_records` | Maximum number of stored pointer rows. Required and finite. |
| `storage` | `max_logical_database_bytes` | Maximum used SQLite bytes, measured as `(page_count - freelist_count) * page_size`. Required and finite. |
| `retention` | `acknowledged_pointer_max_age_days` | Minimum age before a pointer whose deliveries are all read can be purged. Required and positive. |
| `retention` | `traffic_log_max_age_days` | Age after which traffic-log rows can be purged. Required and positive. |
| `limits` | `max_unread_global` | Global unread-delivery cap. Must reserve at least 10 unread deliveries per registered seat. Required and finite. |
| `limits` | `send_per_minute` | Per-seat and per-source pointer request limit; defaults to 60. |
| `limits` | `invalid_per_minute` | Separate per-seat and per-source limit for invalid send attempts; defaults to 60. |
| `limits` | `max_body_bytes` | Request body limit; defaults to 4 KiB and cannot exceed 4 KiB. |
| `limits` | `max_streams_per_seat`, `max_streams_global` | Concurrent stream caps; default to 8 per seat and 128 overall. The global limit must reserve at least one stream per registered seat. |
| `limits` | `max_unread_per_seat` | Per-seat unread limit; defaults to 100 and cannot be lower than the 10-delivery reservation. |
| `limits` | `max_replay_events` | Maximum replay events per stream; defaults to 1,000. |
| `limits` | `max_http_workers` | Maximum concurrent HTTP handlers, including SSE streams; defaults to 32 more than `max_streams_global` and must exceed it. Excess connections receive `503 server_busy`. |
| `limits` | `request_timeout_seconds` | Total time allowed to receive request headers and body; defaults to 10 seconds and does not reset when bytes arrive. |

Ovue reserves 15% physical SQLite headroom above the logical database limit for acknowledgements, token changes, and purge. The operator warning starts at 80% of either storage limit. Purge removes only old pointers whose deliveries are all read and trims traffic logs using their separate retention age. An optional `VACUUM` can shrink the physical file.

## Hostnames and TLS

Host entries are lowercased and matched exactly. Wildcards, IP literals, trailing dots, IDN/punycode names, ports, paths, and schemes are rejected. Add each subdomain or custom domain separately. Ovue never fetches or follows a reference URL. Clients must not follow a redirect to a host outside the allowlist.

The service binds to loopback by default. A non-local listener requires a certificate and private-key path. Place those files under the appropriate host-level access controls; the private key must remain readable only by the service operator.
