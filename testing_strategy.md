# Testing strategy

This document describes how Ovue tests should show that the implementation follows its contract. The repository-level [specification](spec.md) is the source of required behavior. A passing test suite proves only the behavior covered by the tests; acceptance criteria for work not implemented yet remain unverified.

## Start from the contract

For every behavior change:

1. Find the relevant requirement and acceptance criterion in `spec.md`.
2. Write tests for the allowed behavior and the rejected behavior.
3. For a numeric limit, test the value at the limit and the first value beyond it. When useful, also test the value just below the limit.
4. For state changes or multi-recipient actions, check both the intended result and that unrelated records or recipients stay unchanged.
5. Keep a clear connection between the requirement and its test name. Update the tests when the contract changes.

Examples of boundary pairs include a 120-character description being accepted and a 121-character description being rejected, or the maximum recipient count being accepted and one more recipient being rejected. Do not test only a valid example when the contract also promises to reject invalid input.

## Test at the right level

Keep tests beside the code they cover, following the project structure:

| Test area | What it checks |
| --- | --- |
| `utils/test_functions.py` | Small deterministic helpers, such as URL parsing and character checks. |
| `validation/test_validation.py` | Pointer fields, recipient rules, URL policy, allowed values, and numeric boundaries. |
| `storage/test_sqlite.py` | Saved records, transaction behavior, capacity limits, and data retained after reopening SQLite. |
| `send/test_operation.py` | The send operation working across validation and storage, including all-or-nothing behavior. |

When HTTP, SSE, or admin CLI features are implemented, add tests at those boundaries too. Component tests do not replace tests of the externally visible behavior those adapters promise.

## Choose cases deliberately

- Use parameterized tests when several inputs exercise the same rule and expect the same kind of outcome. Give cases readable names when the input alone is not clear.
- Keep separate tests when cases have different setup, side effects, or expected outcomes.
- Check the specific error code and field path promised by the contract, not merely that some error occurred.
- For rejected writes, verify that no partial pointer or delivery was saved.
- For multi-recipient behavior, verify each recipient's state independently.
- For retries, concurrency, and recovery, check ordering, stable IDs, and durable state as required by the specification.
- Use temporary databases and isolated test data so a test does not depend on a developer's local state or test order.
- Keep test comments and docstrings in plain English and explain the behavior being checked.

## Run the suite

Install the development tools and run all tests from the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable '.[dev]'
python -m pytest
```

Run one test file while working on a component:

```sh
python -m pytest ovue/modules/pointers/validation/test_validation.py
```

Before reporting a change, state which tests and other checks were run. Do not describe an acceptance criterion as verified unless an implemented test or other direct check covers it.
