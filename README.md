# Ovue

Ovue is a Python message pointer service. It routes pointers to messages held in external messaging or memory systems. Each pointer includes a reference URL and a short description; Ovue does not host the referenced messages.

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

## Specification

See [spec.md](spec.md) for the service contract.
