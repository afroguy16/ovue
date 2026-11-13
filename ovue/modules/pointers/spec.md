# Pointers module

Author: Okoro (AI Agent)
Human Driver: Jonathan

This document defines the responsibility of the `pointers` module. The repository-level [`spec.md`](../../../spec.md) is authoritative for Ovue's complete contract, HTTP behavior, security requirements, limits, and acceptance criteria. If details differ, follow the repository-level spec.

## Responsibility

The pointers module owns pointer operations and their durable state:

- validate and send a pointer on behalf of an authenticated sender;
- create one independent delivery for each recipient;
- list a seat's inbox and replay its events;
- acknowledge one delivery for its recipient;
- record pointer traffic and remove eligible pointers during purge.

It does not own HTTP parsing, SSE connections, command-line argument parsing, seat registration, or token lifecycle. Those entry points and capabilities call this module through explicit interfaces.

## Boundaries

- The HTTP transport translates requests and stream connections into module operations, then translates results into HTTP responses or SSE events.
- The local admin CLI calls module operations for operator actions, including sending as `operator`, reading its inbox, acknowledging deliveries, reading the traffic log, and purging.
- The seats module supplies authenticated identity and recipient lookup. The pointers module must not accept a sender identity supplied by an agent request body.
- SQLite is accessed through the pointers module's persistence boundary. Transport and CLI code do not issue pointer queries directly.

## Layout

Each concern has its own folder, with its tests beside the code they exercise:

```text
pointers/
├── send/
│   ├── operation.py
│   └── test_operation.py
├── validation/
│   ├── validation.py
│   └── test_validation.py
├── storage/
│   ├── sqlite.py
│   └── test_sqlite.py
└── utils/
    ├── functions.py
    └── test_functions.py
```

```mermaid
flowchart LR
    subgraph Adapters[Outside this module]
        direction TB
        HTTP["(a) HTTP transport"]
        CLI["(b) Local admin CLI"]
        Seats["(c) Seats interface<br/>sender identity and recipient lookup"]
    end

    subgraph PointerModule[Pointers module]
        Send["(d) Send pointer operation"]
        Validate["(e) Validate fields<br/>deduplicate recipients"]
        Transaction["(f) BEGIN IMMEDIATE<br/>check storage and inbox capacity"]
        Persist["(g) Write pointer,<br/>deliveries, and traffic rows"]
        DB[("(h) SQLite")]
        Other["(i) Inbox, replay, ack,<br/>traffic read, and purge"]

        Send --> Validate --> Transaction --> Persist --> DB
        Other -. planned operations .-> DB
    end

    HTTP --> Send
    CLI --> Send
    Seats --> Send

    classDef partial fill:#fef3c7,stroke:#d97706,color:#78350f;
    classDef todo fill:#e5e7eb,stroke:#6b7280,color:#374151;
    class Send,Validate,Transaction,Persist,DB partial;
    class HTTP,CLI,Seats,Other todo;
```

**Implementation status:** 🟨 Partial · ⬜ Not started. Amber marks the send path currently implemented and tested; gray marks adapters, the seats interface, and pointer operations not yet implemented.

| Box | Responsibility |
| --- | --- |
| (a) HTTP transport | Passes an authenticated send request to the module and returns its result. |
| (b) Local admin CLI | Passes operator send requests to the module. |
| (c) Seats interface | Supplies authenticated sender identity and recipient IDs. |
| (d) Send pointer operation | Coordinates validation and durable creation of one pointer and its deliveries. |
| (e) Validation | Checks pointer fields and recipient rules, then collapses duplicate recipient IDs. |
| (f) Send transaction | Serializes storage and unread-inbox capacity checks with pointer creation. |
| (g) Persistence writes | Stores the pointer, one delivery per recipient, and corresponding traffic records atomically. |
| (h) SQLite | Stores pointer, delivery, and traffic-log data for the send slice. |
| (i) Other operations | Inbox, event replay, acknowledgement, traffic-log reading, and purge remain to be implemented. |

## State and consistency

- A pointer and all of its recipient deliveries are persisted atomically before send reports success.
- Each recipient has independent delivery state and event ordering.
- Acknowledgement changes only the addressed recipient's delivery to `read`; repeating the acknowledgement is harmless.
- Send validation, recipient inbox capacity checks, and storage-limit checks occur within the serialized send transaction described in the repository-level spec.
- Purge removes a pointer only when every delivery is `read` and the pointer is older than the configured retention age. It also trims traffic-log rows according to their separate configured age.

## Public operations

The module exposes operations for sending a pointer, listing inbox pages and unread backlog, replaying events after a recipient sequence cursor, acknowledging a delivery, reading the operator traffic log, and purging eligible records.

The exact request and response fields, validation rules, errors, ordering, and retry semantics are defined in the repository-level [`spec.md`](../../../spec.md). The module should expose typed Python inputs and results rather than HTTP request or response objects.
