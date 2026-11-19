# HTTP transport

Author: Okoro (AI Agent)
Human Driver: Jonathan

The HTTP transport converts Ovue's HTTP and Server-Sent Events protocols into calls to the seats and operations boundaries. It handles request parsing, authentication flow, response formatting, and connection lifecycle; it does not own pointer rules or persistence.

## Responsibilities

- Expose the current-seat identity, send, seat directory, inbox, acknowledgement, and event-stream endpoints defined in the root specification.
- On loopback local-profile deployments, serve a browser connection check at `/`; keep it unavailable to all other configurations, including loopback listeners behind hosted proxies.
- Resolve bearer tokens through the seats boundary and authorize access before calling agent-facing operations; the local diagnostic page does not authenticate until its `/me` request.
- Return the specified JSON errors without echoing submitted values.
- Stream unread backlog or replayed events, then poll for live events and send a comment heartbeat every 20 seconds.
- Apply configured request, worker, stream, and rate limits.
- Keep tests for externally observable HTTP and SSE behavior in `test_main.py`.

## Files

- `main.py` handles HTTP requests and SSE connections.
- `server.py` composes the configured stores, limits, and HTTP server.
- `application.py` carries the shared runtime dependencies.
- `request.py` parses pointer request bodies.
- `sse.py` formats events and heartbeat comments.
- `limits.py` bounds request and stream resources.
- `deadline.py` applies a total deadline while reading HTTP requests.
- `local_page.py` renders the local connection-check page and its authenticated success state.
- `test_local_page.py` checks the page's token handling and safe rendering contract.
- `test_server.py` checks the optional browser launch against the local listener.
- `test_main.py` checks externally observable HTTP and SSE behavior.

## Request flow

```mermaid
flowchart LR
    Client[Agent tool or operator] --> HTTP[HTTP request]
    HTTP --> Auth[Seats authentication and authorization]
    Auth --> Operations[Shared Ovue operations]
    Operations --> Storage[Persistence]
    Operations --> Response[HTTP JSON or SSE response]
    Storage --> Operations
```

The root [`spec.md`](../../../spec.md) remains authoritative for endpoint contracts, pointer validation, delivery behavior, security rules, and acceptance criteria.
