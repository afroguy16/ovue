# Configuration reference

This reference describes the configuration Ovue needs for the message pointer MVP. The implementation does not load this configuration yet. The values below are examples; numeric storage and retention values are estimates and require Founder confirmation before deployment.

## Example

```toml
[reference]
# Add only the exact hostnames used by participants. No provider hosts are enabled by default.
allowed_hosts = ["app.notion.com"]

[storage]
# Proposed estimates; measure actual usage and confirm before deployment.
max_pointer_records = 100000
max_logical_database_bytes = 268435456 # 256 MiB

[retention]
# Proposed estimates; measure actual usage and confirm before deployment.
acknowledged_pointer_max_age_days = 30
traffic_log_max_age_days = 90
```

The Notion hostname is one example. For any reference system, configure its exact hostname. Subdomains and custom domains require separate entries. An empty `allowed_hosts` list rejects non-localhost URLs.

## Storage limits

`max_pointer_records` counts pointer rows. The logical database size is `(page_count - freelist_count) * page_size`, measured using SQLite's `PRAGMA page_count`, `PRAGMA freelist_count`, and `PRAGMA page_size`. Ovue warns at 80% of either configured limit.

The physical SQLite file limit is derived as 115% of `max_logical_database_bytes`, rounded up to a whole page, and enforced with `PRAGMA max_page_count`. Sends are refused at the logical limit. The extra physical capacity is reserved for acknowledgements, seat revocation and token rotation, and purge operations. Purge frees pages for reuse; an optional `VACUUM` can shrink the file.

## Retention

`acknowledged_pointer_max_age_days` controls when a pointer becomes eligible for purge. A pointer is removed only after every recipient has acknowledged it and it is older than this age. A pointer with any unread delivery is retained.

`traffic_log_max_age_days` sets an independent retention age for traffic-log rows. The purge command removes log rows older than this age. Both ages are estimates in the example and should be tuned using observed history and storage use.
