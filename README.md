# Ovue

Ovue is a Python message pointer service. It routes pointers to messages held in external messaging or memory systems. Each pointer includes a reference URL and a short description; Ovue does not host the referenced messages.

The implementation is in progress. The package currently provides a CLI help entry point. The server, HTTP/SSE endpoints, durable pointer storage, and administration commands remain to be implemented.

## Reference-host configuration

Each Ovue operator configures the exact hosts their participants use. Ovue enables no provider hosts by default. Host matching is exact; add each hostname separately, including any subdomain or custom domain. An empty allowlist rejects non-localhost URLs.

For example, the config for a deployment using an example service might contain:

```toml
[reference]
allowed_hosts = ["messages.example.org"]
```

For example, a deployment using Notion could configure:

```toml
[reference]
allowed_hosts = ["app.notion.com"]
```

Reference URLs must not contain query strings or fragments. Use the canonical URL without tracking parameters or fragments.

The pointer description accepts printable ASCII only. Characters such as the naira sign (`₦`) and curly quotation marks (`“ ”`) are rejected.

If a pointer is rejected because a recipient's inbox is full, the condition is temporary. The sender can retry after the recipient acknowledges a pointer and an unread slot becomes available.

## Setup

Use Python 3.11 or newer from this project directory.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable .
ovue --help
```

The package can also be run from the project directory with `python -m ovue --help`.

## Specification

See [spec.md](spec.md) for the service contract.
