# Storage

Author: Okoro (AI Agent)
Human Driver: Jonathan

Storage owns durable pointer persistence and the SQLite capacity rules shared by Ovue's data stores. Operations depend on its persistence contract; HTTP and CLI compose the SQLite implementation without managing database queries or transactions themselves.

## Responsibilities

- Persist a pointer, each recipient delivery, and its traffic row in one transaction.
- Enforce pointer-count, logical database-size, and unread-delivery limits atomically.
- Read inbox pages and stream events in recipient sequence order.
- Acknowledge only the recipient's own delivery.
- Retain eligible pointers and traffic history according to the configured purge ages.
- Apply the physical SQLite page cap with recovery headroom.

## Files

- `main.py` defines the pointer storage contract, SQLite implementation, and pointer persistence records.
- `seats.py` persists seat identities and bearer-token hashes in SQLite.
- `utils.py` applies the shared physical SQLite page limit.
- `test_main.py` checks persisted pointer behavior and durability.
- `test_seats.py` checks seat and token persistence behavior.
- `test_utils.py` checks the shared page-limit behavior.

## Boundary

The operations package translates storage capacity failures into application validation issues. Transports do not import SQLite errors or issue queries directly. Storage does not validate HTTP input, authenticate seats, or decide how a client processes a pointer.

SQLite serializes capacity checks and writes with `BEGIN IMMEDIATE`. A successful send is returned only after its pointer, deliveries, and traffic records commit together. Physical page headroom keeps acknowledgements, token administration, and purge available when the logical pointer capacity is reached.
