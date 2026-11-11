# Ovue

Ovue is a Python project for an agent message channel. Its planned contract provides short references to external work, registered seats, durable recipient inboxes, acknowledgements, and SSE delivery across agent tools.

The implementation is in progress. The current code includes a CLI help entry point, message validation, and draft service and SQLite modules. HTTP/SSE serving and the administrative workflows still need implementation and acceptance testing.

## Setup

Use Python 3.11 or newer from this project directory.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable .
ovue --help
```

The package can also be run from the project directory with `python -m ovue --help`.

## Specification documents

- [spec.md](spec.md) contains the earlier reconstructed specification and audit additions.
- [spec-recovered.md](spec-recovered.md) contains the scratch baseline with the recorded security edits through v6 replayed.
- [spec-traceability.md](spec-traceability.md) records the earlier reconstruction audit and its unresolved items.

These documents retain their contents from the Irúo project, including historical package paths and boundaries. They require reconciliation before being treated as one final implementation specification.
