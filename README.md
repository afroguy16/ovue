# Ovue

Ovue is a small, provider-neutral service for sending agents pointers to references in external systems. A pointer contains recipient IDs, a reference URL, a short description, and a kind. Ovue stores the pointer and tracks each recipient's delivery state; the referenced item stays in the system that owns it.

## Run locally

Use Python 3.11 or newer. Install the package and its development tools:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable '.[dev]'
```

Create a local configuration. Add one `--allow-host` option for each exact external hostname you use; omit the options to keep external references disabled.

```sh
ovue init --local --allow-host app.notion.com
```

Start Ovue and open its local connection-check page:

```sh
ovue serve --open-browser
```

In the browser, paste a seat token into the password field to verify access. The page identifies the authenticated seat and shows its inbox endpoint. It sends the token only to Ovue's local `/me` endpoint and does not save it.

In another terminal, register a seat. Its bearer token is displayed once, only when the command is run in a terminal. Save it securely for the seat owner.

```sh
ovue seat create \
  --handle writer --display-name Ese --role Writer
```

The local data directory and SQLite database are restricted to the current OS user. Non-local listeners require TLS certificate and key paths in the configuration.

## Reference hosts

Configure exact hostnames in `[reference].allowed_hosts`. Ovue enables no provider hosts by default, accepts no wildcard entries, and never fetches a reference URL. For example, a Notion workspace using `app.notion.com` can set:

```toml
[reference]
allowed_hosts = ["app.notion.com"]
```

Use the exact host in links shared by your team. Ovue rejects reference URLs with query strings or fragments; use the canonical URL without tracking parameters.

Pointer descriptions allow printable ASCII only. For example, the naira sign and curly quotation marks are rejected. If a recipient's inbox is full, the sender can retry after that recipient acknowledges a pointer.

## HTTP examples

These examples use `curl`. The helper prompts for the token each time and passes it to `curl` through standard input, so it does not appear in the command history, process arguments, or a file.

```sh
ovue_curl() {
  python -c 'import getpass, sys; token = getpass.getpass("Seat token: "); sys.stdout.write("header = \"Authorization: Bearer " + token + "\"\n")' | curl --config - "$@"
}

BASE_URL=http://127.0.0.1:8765
SEAT_ID='<recipient-seat-id>'

# Find IDs and handles for registered seats and the operator.
ovue_curl "$BASE_URL/seats"

# Identify the seat associated with the token entered by the helper.
ovue_curl "$BASE_URL/me"

# Send a pointer to a recipient ID.
ovue_curl -X POST -H 'Content-Type: application/json' \
  --data '{"to":["<recipient-seat-id>"],"ref":{"url":"https://app.notion.com/<canonical-page-path>","title":"CT-2"},"description":"Ready for review","kind":"done"}' \
  "$BASE_URL/send"

# Read an inbox page. Use unread=1 for unacknowledged deliveries.
ovue_curl "$BASE_URL/inbox/$SEAT_ID?unread=1"

# Acknowledge one delivery after your own work is complete.
ovue_curl -X POST "$BASE_URL/ack/<delivery-id>"

# Receive the unread backlog and then live events. Resume with Last-Event-ID.
ovue_curl -N -H 'Last-Event-ID: <recipient-sequence>' "$BASE_URL/stream/$SEAT_ID"
```

The local admin commands also support token rotation and revocation, sending and acknowledging as the operator, reading traffic history, and purging expired records. Run `ovue --help` for the command list.

## Tests and checks

Install the development tools using the setup command above, then run:

```sh
python -m pytest
ruff check .
ruff format --check .
mypy
```

See [`testing_strategy.md`](testing_strategy.md) for how tests are selected. The full service contract is in [`spec.md`](spec.md).
