# Contributing to Ovue

This guide describes how to make and review changes to Ovue.

## Read first

Before changing behavior, read:

- [README.md](README.md) for the project overview and setup;
- [spec.md](spec.md) for the service contract and required behavior;
- [configuration.md](configuration.md) for the proposed configuration shape and limits;
- the code and colocated tests for the part you are changing.

If a change affects the pointer contract, delivery behavior, security rules, or configuration requirements, update the specification in the same change. The specification describes required behavior; it does not prove that the implementation meets it.

## Work in focused slices

- Make one focused change per branch. Each change should have one clear outcome and be independently reviewable and revertible.
- Work vertically through the affected behavior: define or update the requirement, implement it, add or update colocated tests, and verify the slice before expanding scope.
- Keep related domain code together. Split responsibilities into focused modules and avoid God files.
- Place tests beside the code they exercise.
- Include line-by-line explanatory comments when adding code, as required for this project is a simple way for developers to understand how python works.

## Preserve Ovue's boundaries

- Ovue stores and routes pointers to external messages. It does not store the referenced message content or become a conversation system.
- Keep the service independent of any agent provider or reference platform. Provider hostnames belong in operator configuration, never as built-in defaults.
- Treat pointer fields and referenced content as untrusted. Do not put credentials or private data in URLs, descriptions, logs, examples, or tests.
- Preserve per-recipient delivery state and all-or-nothing behavior for multi-recipient sends.
- Do not claim a security or delivery guarantee unless the code and tests establish it.

## Set up and verify

Use Python 3.11 or newer. Install the development tools declared in `pyproject.toml` with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --group dev
```

Run the checks relevant to your change:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Add or update tests for changed behavior. Report which checks you ran and any that remain unrun; do not describe an unrun check as passing.

## Branches and commits

- Branch from an up-to-date `main`; do not push directly to `main`.
- Use one branch per focused change, named `<type>/<scope>-<short-description>`, for example `feat/send-atomic-capacity` or `docs/config-reference`.
- Use scoped conventional commit subjects: `type(scope): description`. Choose a functional scope, such as `feat(send): reject full inboxes`, `fix(storage): reserve SQLite headroom`, `docs(config): clarify host allowlists`, or `test(stream): cover replay recovery`.
- Stage specific files intentionally. Avoid blanket staging commands so unrelated work does not enter the commit.
- Keep commits free of credentials, local databases, logs, virtual environments, and generated files.

Open a pull request for changes intended for `main`. Describe the problem, the resulting behavior, relevant specification changes, and verification performed. Keep the branch focused and request review before merging.

## Ready to merge

A change is ready when it has one clear purpose, follows the specification, includes relevant colocated tests and documentation, passes the applicable checks, and identifies any remaining limitations for reviewers.
