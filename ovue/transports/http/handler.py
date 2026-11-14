"""Translate pointer and seat HTTP requests into module operations."""

from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from io import BufferedReader
from typing import Protocol, cast
from urllib.parse import parse_qs, urlsplit

from ovue.modules.pointers.acknowledgement.operation import acknowledge
from ovue.modules.pointers.inbox.operation import get_inbox
from ovue.modules.pointers.monitoring.operation import warn_if_near_capacity
from ovue.modules.pointers.send.operation import Sender, send
from ovue.modules.pointers.storage.sqlite import CapacityReached
from ovue.modules.pointers.stream.operation import events_after, start_stream
from ovue.modules.pointers.validation.validation import Issue, IssueRejected, Policy
from ovue.modules.seats.directory.operation import seat_directory
from ovue.modules.seats.entities import AuthenticatedSeat
from ovue.transports.http.application import HTTPApplication
from ovue.transports.http.deadline import DeadlineReader
from ovue.transports.http.request import parse_pointer_payload
from ovue.transports.http.sse import encode_event, heartbeat


class _ServerWithApplication(Protocol):
    """Describe the request-server attribute attached by the HTTP factory."""

    application: HTTPApplication


class OvueRequestHandler(BaseHTTPRequestHandler):
    """Handle one request without logging its path, headers, or body."""

    def setup(self) -> None:
        """Apply a total deadline to reading this connection's HTTP request."""
        super().setup()
        timeout = self._application().settings.request_timeout_seconds
        self.rfile = cast(
            BufferedReader,
            DeadlineReader(cast(BufferedReader, self.rfile), self.connection, timeout),
        )

    def handle(self) -> None:
        """Close peers that exceed the request deadline without a traceback."""
        try:
            super().handle()
        except TimeoutError:
            self.close_connection = True

    def do_GET(self) -> None:
        """Route authenticated directory, inbox, and stream requests."""
        app = self._application()
        split = urlsplit(self.path)
        try:
            query = parse_qs(split.query, max_num_fields=8)
        except ValueError:
            self._validation_error(
                (Issue("too_many_query_fields", "Too many query fields", ()),)
            )
            return
        if "token" in query:
            self._validation_error(
                (
                    Issue(
                        "field_not_allowed",
                        "Tokens are accepted only in the Authorization header",
                        ("token",),
                    ),
                )
            )
            return
        seat = self._authenticate(app)
        if seat is None:
            return
        if split.path == "/seats":
            self._json(HTTPStatus.OK, {"items": seat_directory(app.seats)})
            return
        parts = split.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "inbox":
            self._inbox(app, seat, parts[1], split.query)
            return
        if len(parts) == 2 and parts[0] == "stream":
            self._stream(app, seat, parts[1])
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found")

    def do_POST(self) -> None:
        """Route pointer sends and recipient acknowledgements."""
        app = self._application()
        split = urlsplit(self.path)
        try:
            query = parse_qs(split.query, max_num_fields=8)
        except ValueError:
            self._validation_error(
                (Issue("too_many_query_fields", "Too many query fields", ()),)
            )
            return
        if "token" in query:
            self._validation_error(
                (
                    Issue(
                        "field_not_allowed",
                        "Tokens are accepted only in the Authorization header",
                        ("token",),
                    ),
                )
            )
            return
        seat = self._authenticate(app)
        if seat is None:
            return
        if split.path == "/send":
            self._send(app, seat)
            return
        parts = split.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "ack":
            try:
                acknowledge(app.pointers, parts[1], recipient_id=seat.id)
            except LookupError:
                self._error(HTTPStatus.NOT_FOUND, "not_found")
                return
            self._json(HTTPStatus.OK, {"delivery_id": parts[1], "state": "read"})
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found")

    def log_message(self, format: str, *args: object) -> None:
        """Avoid placing request paths or pointer content in server logs."""

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        """Return parser and unsupported-method errors as JSON without echoing input."""
        try:
            status = HTTPStatus(code)
        except ValueError:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        if status == HTTPStatus.NOT_IMPLEMENTED:
            status = HTTPStatus.METHOD_NOT_ALLOWED
        if status == HTTPStatus.REQUEST_URI_TOO_LONG:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        if status == HTTPStatus.BAD_REQUEST:
            self._validation_error(
                (Issue("malformed_request", "Request is invalid", ()),)
            )
            return
        error_code = {
            HTTPStatus.NOT_FOUND: "not_found",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "payload_too_large",
            HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
        }.get(status, "internal_error")
        self._json(
            status,
            {"error": error_code},
            headers=(
                {"Allow": "GET, POST"}
                if status == HTTPStatus.METHOD_NOT_ALLOWED
                else None
            ),
        )

    def _send(self, app: HTTPApplication, seat: AuthenticatedSeat) -> None:
        """Parse, validate, rate-limit, and persist one pointer submission."""
        source = str(self.client_address[0])
        for bucket in (f"source:{source}", f"seat:{seat.id}"):
            retry = app.rate_limiter.check(
                bucket,
                maximum=app.settings.send_per_minute,
            )
            if retry is not None:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited", retry)
                return
        body = self._read_json(app, seat, app.settings.max_body_bytes)
        if body is None:
            return
        try:
            payload = parse_pointer_payload(body)
            result = send(
                payload,
                sender=Sender(seat.id, seat.display_name, seat.role),
                known_seat_ids=app.seats.known_seat_ids(),
                policy=Policy(
                    allowed_hosts=app.settings.allowed_hosts,
                    max_pointer_records=app.settings.max_pointer_records,
                    max_logical_database_bytes=app.settings.max_logical_database_bytes,
                    max_unread_per_seat=app.settings.max_unread_per_seat,
                    local_deployment=app.settings.local_deployment,
                    max_unread_global=app.settings.max_unread_global,
                ),
                storage=app.pointers,
            )
        except IssueRejected as error:
            self._report_send_validation_error(app, seat, error.issues)
            return
        except CapacityReached as error:
            self._validation_error((Issue(error.code, error.message, error.path),))
            return
        deliveries = [
            {
                "delivery_id": delivery.delivery_id,
                "recipient_id": delivery.recipient_id,
                "state": delivery.state,
            }
            for delivery in result.deliveries
        ]
        warn_if_near_capacity(
            app.pointers,
            max_pointer_records=app.settings.max_pointer_records,
            max_logical_database_bytes=app.settings.max_logical_database_bytes,
        )
        self._json(
            HTTPStatus.CREATED,
            {"pointer_id": result.pointer_id, "deliveries": deliveries},
        )

    def _inbox(
        self,
        app: HTTPApplication,
        seat: AuthenticatedSeat,
        requested_seat_id: str,
        raw_query: str,
    ) -> None:
        """Return one authorized inbox page with validated filters and cursor."""
        if requested_seat_id != seat.id:
            self._error(HTTPStatus.FORBIDDEN, "forbidden")
            return
        try:
            query = parse_qs(
                raw_query,
                keep_blank_values=True,
                max_num_fields=4,
            )
            unread_text = _single_query_value(query, "unread")
            if unread_text not in (None, "0", "1"):
                raise ValueError("Unread filter is invalid")
            limit_text = _single_query_value(query, "limit")
            limit = 50 if limit_text is None else int(limit_text)
            cursor = _single_query_value(query, "cursor")
            page = get_inbox(
                app.pointers,
                seat.id,
                unread=None if unread_text is None else unread_text == "1",
                limit=limit,
                cursor=cursor,
            )
        except ValueError:
            self._validation_error(
                (Issue("invalid_cursor_or_limit", "Inbox query is invalid", ()),)
            )
            return
        self._json(
            HTTPStatus.OK, {"items": page.items, "next_cursor": page.next_cursor}
        )

    def _stream(
        self,
        app: HTTPApplication,
        seat: AuthenticatedSeat,
        requested_seat_id: str,
    ) -> None:
        """Send unread backlog, replay, and live events over one SSE connection."""
        if requested_seat_id != seat.id:
            self._error(HTTPStatus.FORBIDDEN, "forbidden")
            return
        last_event_id = self.headers.get("Last-Event-ID")
        try:
            start = start_stream(
                app.pointers,
                seat.id,
                last_event_id=last_event_id,
                replay_limit=app.settings.max_replay_events,
                unread_limit=app.settings.max_unread_per_seat,
            )
        except ValueError:
            self._validation_error(
                (Issue("invalid_cursor", "Event cursor is invalid", ()),)
            )
            return
        except RuntimeError:
            self._error(
                HTTPStatus.CONFLICT,
                "replay_unavailable",
                message="Recover via GET /inbox/{seat-id}?unread=1",
            )
            return

        with app.streams.open(seat.id) as accepted:
            if not accepted:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited", 1)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.connection.settimeout(10)
            sequence = start.next_sequence
            try:
                for event in start.events:
                    self.wfile.write(encode_event(event))
                    sequence = max(sequence, cast(int, event["event_id"]))
                self.wfile.flush()
                last_heartbeat = time.monotonic()
                token = self._bearer_token()
                if token is None:
                    return
                while not app.stopping.is_set() and app.seats.is_token_active(
                    seat.id, token
                ):
                    try:
                        events = events_after(
                            app.pointers,
                            seat.id,
                            sequence,
                            replay_limit=app.settings.max_replay_events,
                        )
                    except RuntimeError:
                        break
                    for event in events:
                        self.wfile.write(encode_event(event))
                        sequence = max(sequence, cast(int, event["event_id"]))
                    now = time.monotonic()
                    if now - last_heartbeat >= 20:
                        self.wfile.write(heartbeat())
                        last_heartbeat = now
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                return

    def _read_json(
        self,
        app: HTTPApplication,
        seat: AuthenticatedSeat,
        maximum_bytes: int,
    ) -> object | None:
        """Read a bounded JSON request body without echoing malformed input."""
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self._report_send_validation_error(
                app,
                seat,
                (Issue("invalid_content_length", "Content-Length is required", ()),),
            )
            return None
        if length > maximum_bytes:
            self.close_connection = True
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large")
            return None
        try:
            return cast(object, json.loads(self.rfile.read(length).decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._report_send_validation_error(
                app,
                seat,
                (Issue("invalid_json", "Request body must be valid JSON", ()),),
            )
            return None

    def _report_send_validation_error(
        self,
        app: HTTPApplication,
        seat: AuthenticatedSeat,
        issues: tuple[Issue, ...],
    ) -> None:
        """Count invalid send attempts separately before returning their issues."""
        source = str(self.client_address[0])
        retries = (
            app.rate_limiter.check(
                f"invalid-source:{source}",
                maximum=app.settings.invalid_per_minute,
            ),
            app.rate_limiter.check(
                f"invalid-seat:{seat.id}",
                maximum=app.settings.invalid_per_minute,
            ),
        )
        retry = max((value for value in retries if value is not None), default=None)
        if retry is not None:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited", retry)
            return
        self._validation_error(issues)

    def _authenticate(self, app: HTTPApplication) -> AuthenticatedSeat | None:
        """Authenticate only the bearer token in the Authorization header."""
        source = str(self.client_address[0])
        retry = app.rate_limiter.check(f"auth:{source}", maximum=120)
        if retry is not None:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited", retry)
            return None
        token = self._bearer_token()
        if token is None:
            self._error(HTTPStatus.UNAUTHORIZED, "unauthorized")
            return None
        try:
            return app.seats.authenticate(token)
        except PermissionError:
            self._error(HTTPStatus.UNAUTHORIZED, "unauthorized")
            return None

    def _bearer_token(self) -> str | None:
        """Return a syntactically valid bearer value without accepting query tokens."""
        authorization = self.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or " " in token:
            return None
        return token

    def _application(self) -> HTTPApplication:
        """Return the application object attached to this server instance."""
        return cast(_ServerWithApplication, self.server).application

    def _validation_error(self, issues: tuple[Issue, ...]) -> None:
        """Return every safe validation issue without submitted values."""
        self._json(
            HTTPStatus.BAD_REQUEST,
            {
                "error": "validation_failed",
                "issues": [
                    {
                        "path": list(issue.path),
                        "code": issue.code,
                        "message": issue.message,
                        **(
                            {"max": issue.max_value}
                            if issue.max_value is not None
                            else {}
                        ),
                    }
                    for issue in issues
                ],
            },
        )

    def _error(
        self,
        status: HTTPStatus,
        code: str,
        retry_after_seconds: int | None = None,
        *,
        message: str | None = None,
    ) -> None:
        """Return a top-level error using the agreed JSON error contract."""
        body: dict[str, object] = {"error": code}
        if retry_after_seconds is not None:
            body["retry_after_seconds"] = retry_after_seconds
        if message is not None:
            body["message"] = message
        self._json(status, body)

    def _json(
        self,
        status: HTTPStatus,
        body: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Write one compact JSON response with no caching."""
        encoded = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode(
            "ascii"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    """Return an optional unique query parameter without accepting duplicates."""
    values = query.get(key)
    if values is None:
        return None
    if len(values) != 1:
        raise ValueError("Query parameter is repeated")
    return values[0]
