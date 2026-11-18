# Seats

Author: Okoro (AI Agent)
Human Driver: Jonathan

The seats package owns registered identities, handles, authentication, the authenticated directory, and token lifecycle operations. It provides the identity and recipient lookup used by HTTP, CLI, and pointer operations. SQLite persistence remains in `ovue/storage/`.

## Responsibilities

- Create and list registered seats without exposing token material.
- Normalize handles and reserve the Founder identity.
- Resolve bearer tokens to authenticated seat identities.
- Rotate and revoke tokens while keeping seat IDs stable.
- Provide seat IDs to pointer validation and expose a safe directory including the operator.
- Preserve global stream and unread-capacity reservations when creating a seat.

## Files

- `main.py` provides the seats interface and operations.
- `entities.py` defines registered and authenticated seat data.
- `utils.py` validates and normalizes handles.
- `test_main.py` checks seat operations and directory behavior.
- `test_utils.py` checks handle validation.

The storage adapter owns SQLite queries and hashed token persistence. HTTP and CLI call this package rather than implementing seat rules or calling the storage adapter directly.
