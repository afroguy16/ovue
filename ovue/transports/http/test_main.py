"""Check externally visible HTTP, SSE, access-control, and request-limit behavior."""

import http.client
import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ovue.configuration import Settings
from ovue.storage.seats import SeatStorage
from ovue.transports.http import main as http_main
from ovue.transports.http.server import OvueHTTPServer, create_server


def make_settings(
    tmp_path: Path,
    *,
    send_limit: int = 60,
    invalid_limit: int = 60,
    max_http_workers: int = 160,
    request_timeout_seconds: int = 10,
    max_streams_global: int = 128,
) -> Settings:
    """Build local test settings with bounded storage and an ephemeral port."""
    return Settings(
        allowed_hosts=frozenset({"work.example.org"}),
        data_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        max_pointer_records=100,
        max_logical_database_bytes=10_000_000,
        pointer_age_days=30,
        log_age_days=90,
        max_unread_global=1000,
        tls_certfile=None,
        tls_keyfile=None,
        send_per_minute=send_limit,
        invalid_per_minute=invalid_limit,
        max_http_workers=max_http_workers,
        request_timeout_seconds=request_timeout_seconds,
        max_streams_global=max_streams_global,
        local_profile=True,
    )


def create_seats(
    database_path: Path,
    *,
    max_logical_database_bytes: int = 10_000_000,
) -> tuple[str, str, str, str]:
    """Create sender and recipient seats and return IDs and one-time tokens."""
    storage = SeatStorage(
        database_path,
        max_logical_database_bytes=max_logical_database_bytes,
    )
    sender, sender_token = storage.create_seat("writer", "Ese", "Writer")
    recipient, recipient_token = storage.create_seat("reviewer", "Ari", "Reviewer")
    storage.close()
    return sender.id, sender_token, recipient.id, recipient_token


@pytest.fixture
def http_server(
    tmp_path: Path,
) -> Iterator[tuple[OvueHTTPServer, str, str, str, str]]:
    """Run the local server in a background thread and close it after a test."""
    settings = make_settings(tmp_path)
    sender_id, sender_token, recipient_id, recipient_token = create_seats(
        settings.database_path,
        max_logical_database_bytes=settings.max_logical_database_bytes,
    )
    server = create_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, sender_id, sender_token, recipient_id, recipient_token
    finally:
        server.shutdown()
        server.server_close()
        server.application.pointers.close()
        server.application.seats.close()
        thread.join(timeout=2)


def request(
    server: Any,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: object | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """Send one HTTP request and decode its response body."""
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=3)
    request_headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    if headers:
        request_headers.update(headers)
    if body is None:
        encoded = None
    elif isinstance(body, bytes):
        encoded = body
    else:
        encoded = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=encoded, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    status = response.status
    connection.close()
    if not data:
        return status, {}
    try:
        return status, json.loads(data)
    except json.JSONDecodeError:
        return status, data


def pointer_body(
    recipient_id: str, *, recipients: list[str] | None = None
) -> dict[str, object]:
    """Return a valid HTTP pointer body addressed to the test reviewer."""
    return {
        "to": recipients or [recipient_id],
        "ref": {"url": "https://work.example.org/items/42", "title": "CT-2"},
        "description": "Ready for review",
        "kind": "done",
    }


def test_send_directory_inbox_ack_and_cross_seat_access(http_server: Any) -> None:
    """Send a pointer, discover seats, read the inbox, and acknowledge safely."""
    server, sender_id, sender_token, recipient_id, recipient_token = http_server
    status, sent = request(
        server, "POST", "/send", token=sender_token, body=pointer_body(recipient_id)
    )
    assert status == 201
    assert isinstance(sent, dict)
    delivery_id = sent["deliveries"][0]["delivery_id"]

    status, directory = request(server, "GET", "/seats", token=recipient_token)
    assert status == 200
    assert isinstance(directory, dict)
    assert directory["items"][-1] == {
        "id": "operator",
        "handle": "operator",
        "display_name": "Operator",
        "role": "operator",
    }
    assert "token" not in json.dumps(directory).lower()

    status, identity = request(server, "GET", "/me", token=recipient_token)
    assert status == 200
    assert identity == {
        "id": recipient_id,
        "handle": "reviewer",
        "display_name": "Ari",
        "role": "Reviewer",
    }

    status, inbox = request(
        server, "GET", f"/inbox/{recipient_id}?unread=1", token=recipient_token
    )
    assert status == 200
    assert isinstance(inbox, dict)
    assert inbox["items"][0]["state"] == "unread"

    status, forbidden = request(
        server, "GET", f"/inbox/{sender_id}", token=recipient_token
    )
    assert status == 403
    assert forbidden == {"error": "forbidden"}

    status, acknowledged = request(
        server, "POST", f"/ack/{delivery_id}", token=recipient_token
    )
    assert status == 200
    assert acknowledged == {"delivery_id": delivery_id, "state": "read"}


def test_local_root_serves_connection_check_without_auth(http_server: Any) -> None:
    """Serve a no-store, same-origin token form only on the loopback service."""
    server, *_ = http_server
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=3)
    connection.request("GET", "/")
    response = connection.getresponse()
    page = response.read().decode("utf-8")

    assert response.status == 200
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Referrer-Policy") == "no-referrer"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert "connect-src 'self'" in response.getheader("Content-Security-Policy", "")
    assert 'type="password"' in page
    assert 'fetch("/me"' in page
    assert 'id="seat-name"' in page
    assert 'id="inbox-endpoint"' in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page
    assert "textContent" in page
    connection.close()


def test_local_root_is_hidden_without_local_profile(http_server: Any) -> None:
    """Keep the browser check behind both the marker and loopback binding."""
    server, *_ = http_server
    server.application.settings = replace(
        server.application.settings, local_profile=False
    )

    status, body = request(server, "GET", "/")

    assert status == 404
    assert body == {"error": "not_found"}

    server.application.settings = replace(
        server.application.settings, host="0.0.0.0", local_profile=True
    )
    status, body = request(server, "GET", "/")

    assert status == 404
    assert body == {"error": "not_found"}


def test_http_rejects_body_sender_without_echoing_submitted_values(
    http_server: Any,
) -> None:
    """Reject a body-supplied sender and report every structural issue safely."""
    server, _, sender_token, recipient_id, _ = http_server
    status, error = request(
        server,
        "POST",
        "/send",
        token=sender_token,
        body={"from": "secret-seat-name", "to": recipient_id, "ref": {}},
    )

    assert status == 400
    assert isinstance(error, dict)
    paths = {tuple(issue["path"]) for issue in error["issues"]}
    assert {("from",), ("to",), ("ref", "url"), ("description",), ("kind",)} <= paths
    assert "secret-seat-name" not in json.dumps(error)


def test_http_returns_the_same_not_found_for_foreign_and_unknown_delivery_ids(
    http_server: Any,
) -> None:
    """Prevent one seat from probing whether another seat's delivery ID exists."""
    server, sender_id, sender_token, recipient_id, recipient_token = http_server
    _, sent = request(
        server,
        "POST",
        "/send",
        token=sender_token,
        body=pointer_body(recipient_id),
    )
    delivery_id = sent["deliveries"][0]["delivery_id"]

    foreign_status, foreign = request(
        server, "POST", f"/ack/{delivery_id}", token=sender_token
    )
    unknown_status, unknown = request(
        server, "POST", "/ack/not-a-delivery", token=recipient_token
    )

    assert foreign_status == unknown_status == 404
    assert foreign == unknown == {"error": "not_found"}


def test_http_requires_a_bearer_header_and_ignores_no_query_token(
    http_server: Any,
) -> None:
    """Authenticate only through Authorization and never through a URL query."""
    server, _, _, _, recipient_token = http_server
    status, error = request(
        server,
        "GET",
        f"/seats?token={recipient_token}",
        token="",
    )

    assert status == 400
    assert error == {
        "error": "validation_failed",
        "issues": [
            {
                "path": ["token"],
                "code": "field_not_allowed",
                "message": "Tokens are accepted only in the Authorization header",
            }
        ],
    }

    status, error = request(server, "GET", "/seats", token="invalid-token")
    assert status == 401
    assert error == {"error": "unauthorized"}

    status, error = request(server, "GET", "/me")
    assert status == 401
    assert error == {"error": "unauthorized"}


def test_http_parser_errors_use_json_without_echoing_the_request(
    http_server: Any,
) -> None:
    """Keep unsupported methods and excessive query fields inside the JSON contract."""
    server, _, _, _, recipient_token = http_server

    status, error = request(server, "PUT", "/seats", token=recipient_token)

    assert status == 405
    assert error == {"error": "method_not_allowed"}

    status, error = request(
        server,
        "GET",
        "/seats?a=1&b=2&c=3&d=4&e=5&f=6&g=7&h=8&i=9",
        token=recipient_token,
    )

    assert status == 400
    assert error["error"] == "validation_failed"
    assert "a=1" not in json.dumps(error)


def test_http_server_bounds_workers_and_expires_slow_request_headers(
    tmp_path: Path,
) -> None:
    """Reject overload and free workers when a peer exceeds the request deadline."""
    settings = make_settings(
        tmp_path,
        max_http_workers=3,
        request_timeout_seconds=1,
        max_streams_global=2,
    )
    create_seats(
        settings.database_path,
        max_logical_database_bytes=settings.max_logical_database_bytes,
    )
    server = create_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    slow_connections: list[socket.socket] = []
    try:
        for _ in range(settings.max_http_workers):
            address = server.server_address
            connection = socket.create_connection(
                (str(address[0]), int(address[1])),
                timeout=2,
            )
            connection.sendall(b"GET /seats HTTP/1.1\r\nHost:")
            slow_connections.append(connection)

        status, body = request(server, "GET", "/seats", token="invalid-token")
        assert status == 503
        assert body == {"error": "server_busy"}

        time.sleep(settings.request_timeout_seconds + 0.1)
        status, body = request(server, "GET", "/seats", token="invalid-token")
        assert status == 401
        assert body == {"error": "unauthorized"}
    finally:
        for connection in slow_connections:
            connection.close()
        server.shutdown()
        server.server_close()
        server.application.pointers.close()
        server.application.seats.close()
        thread.join(timeout=2)


def test_http_validation_errors_include_relevant_limits_without_echoing_values(
    http_server: Any,
) -> None:
    """Include configured limits in issues while keeping submitted text private."""
    server, _, sender_token, recipient_id, _ = http_server
    body = pointer_body(recipient_id)
    body["description"] = "private " + "x" * 120

    status, error = request(server, "POST", "/send", token=sender_token, body=body)

    assert status == 400
    issue = next(issue for issue in error["issues"] if issue["path"] == ["description"])
    assert issue["code"] == "too_long"
    assert issue["max"] == 120
    assert "private" not in json.dumps(error)


def test_http_rejects_oversized_body_and_rate_limits_sends(tmp_path: Path) -> None:
    """Return 413 for oversized requests and 429 when a seat exceeds its send rate."""
    settings = make_settings(tmp_path, send_limit=3)
    _, sender_token, recipient_id, _ = create_seats(
        settings.database_path,
        max_logical_database_bytes=settings.max_logical_database_bytes,
    )
    server = create_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, error = request(
            server,
            "POST",
            "/send",
            token=sender_token,
            body=b" " * 4097,
            headers={"Content-Length": "4097", "Content-Type": "application/json"},
        )
        assert status == 413
        assert error == {"error": "payload_too_large"}

        status, _ = request(
            server, "POST", "/send", token=sender_token, body=pointer_body(recipient_id)
        )
        assert status == 201
        status, _ = request(
            server, "POST", "/send", token=sender_token, body=pointer_body(recipient_id)
        )
        assert status == 201
        status, error = request(
            server, "POST", "/send", token=sender_token, body=pointer_body(recipient_id)
        )
        assert status == 429
        assert isinstance(error, dict)
        assert error["error"] == "rate_limited"
        assert error["retry_after_seconds"] > 0
    finally:
        server.shutdown()
        server.server_close()
        server.application.pointers.close()
        server.application.seats.close()
        thread.join(timeout=2)


def test_http_tracks_invalid_sends_separately_from_valid_send_rate(
    tmp_path: Path,
) -> None:
    """Rate-limit repeated invalid payloads without blocking a valid send early."""
    settings = make_settings(tmp_path, send_limit=10, invalid_limit=1)
    _, sender_token, recipient_id, _ = create_seats(
        settings.database_path,
        max_logical_database_bytes=settings.max_logical_database_bytes,
    )
    server = create_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    invalid_body = pointer_body(recipient_id)
    invalid_body["ref"] = {"url": "https://outside.example/items/42"}
    try:
        first_status, first_error = request(
            server,
            "POST",
            "/send",
            token=sender_token,
            body=invalid_body,
        )
        second_status, second_error = request(
            server,
            "POST",
            "/send",
            token=sender_token,
            body=invalid_body,
        )
        valid_status, _ = request(
            server,
            "POST",
            "/send",
            token=sender_token,
            body=pointer_body(recipient_id),
        )

        assert first_status == 400
        assert first_error["error"] == "validation_failed"
        assert second_status == 429
        assert second_error["error"] == "rate_limited"
        assert valid_status == 201
    finally:
        server.shutdown()
        server.server_close()
        server.application.pointers.close()
        server.application.seats.close()
        thread.join(timeout=2)


def test_two_live_streams_each_receive_the_pointer_event(http_server: Any) -> None:
    """Fan out a new event to every concurrently open stream for the seat."""
    server, _, sender_token, recipient_id, recipient_token = http_server
    stream_connections = [
        http.client.HTTPConnection(
            server.server_address[0], server.server_address[1], timeout=3
        )
        for _ in range(2)
    ]
    responses = []
    try:
        for connection in stream_connections:
            connection.request(
                "GET",
                f"/stream/{recipient_id}",
                headers={"Authorization": f"Bearer {recipient_token}"},
            )
            response = connection.getresponse()
            assert response.status == 200
            responses.append(response)
        request(
            server,
            "POST",
            "/send",
            token=sender_token,
            body=pointer_body(recipient_id),
        )

        received_ids = []
        for response in responses:
            event_id = response.readline().decode("ascii").strip()
            data_line = response.readline().decode("ascii").strip()
            response.readline()
            assert event_id.startswith("id: ")
            assert data_line.startswith("data: ")
            received_ids.append(
                json.loads(data_line.removeprefix("data: "))["delivery_id"]
            )
        assert received_ids[0] == received_ids[1]
    finally:
        for connection in stream_connections:
            connection.close()


def test_idle_stream_sends_heartbeats_and_stays_open(
    http_server: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an idle stream connected while three heartbeat intervals pass."""
    server, _, _, recipient_id, recipient_token = http_server
    real_sleep = time.sleep

    class AcceleratedClock:
        """Advance stream time quickly while preserving real socket behavior."""

        current_time = 0.0

        def monotonic(self) -> float:
            """Advance ten simulated seconds for each stream clock check."""
            self.current_time += 10
            return self.current_time

        def sleep(self, seconds: float) -> None:
            """Yield briefly so the stream thread can serve the client."""
            real_sleep(0.005)

    monkeypatch.setattr(http_main, "time", AcceleratedClock())
    connection = http.client.HTTPConnection(
        server.server_address[0], server.server_address[1], timeout=3
    )
    try:
        connection.request(
            "GET",
            f"/stream/{recipient_id}",
            headers={"Authorization": f"Bearer {recipient_token}"},
        )
        response = connection.getresponse()
        assert response.status == 200

        for _ in range(3):
            assert response.readline() == b": keep-alive\n"
            assert response.readline() == b"\n"
    finally:
        connection.close()


def test_stream_replays_after_last_event_id_and_repeats_stable_delivery_id(
    http_server: Any,
) -> None:
    """Resume from the recipient sequence and preserve delivery identity on repeats."""
    server, _, sender_token, recipient_id, recipient_token = http_server
    _, sent = request(
        server,
        "POST",
        "/send",
        token=sender_token,
        body=pointer_body(recipient_id),
    )
    delivery_id = sent["deliveries"][0]["delivery_id"]

    def read_event(last_event_id: str | None) -> tuple[str, dict[str, Any]]:
        """Open one stream and read a complete event before closing it."""
        connection = http.client.HTTPConnection(
            server.server_address[0], server.server_address[1], timeout=3
        )
        headers = {"Authorization": f"Bearer {recipient_token}"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = last_event_id
        connection.request("GET", f"/stream/{recipient_id}", headers=headers)
        response = connection.getresponse()
        event_id = response.readline().decode("ascii").strip().removeprefix("id: ")
        data = response.readline().decode("ascii").strip().removeprefix("data: ")
        response.readline()
        connection.close()
        return event_id, json.loads(data)

    first_sequence, first_event = read_event(None)
    second_sequence, second_event = read_event("0")
    assert first_sequence == second_sequence == "1"
    assert first_event["delivery_id"] == second_event["delivery_id"] == delivery_id

    connection = http.client.HTTPConnection(
        server.server_address[0], server.server_address[1], timeout=3
    )
    connection.request(
        "GET",
        f"/stream/{recipient_id}",
        headers={
            "Authorization": f"Bearer {recipient_token}",
            "Last-Event-ID": "999",
        },
    )
    response = connection.getresponse()
    assert response.status == 400
    error = json.loads(response.read())
    assert error["error"] == "validation_failed"
    connection.close()


def test_revoking_a_token_closes_its_open_stream(http_server: Any) -> None:
    """Stop an active SSE connection soon after its bearer token is revoked."""
    server, _, _, recipient_id, recipient_token = http_server
    connection = http.client.HTTPConnection(
        server.server_address[0], server.server_address[1], timeout=3
    )
    connection.request(
        "GET",
        f"/stream/{recipient_id}",
        headers={"Authorization": f"Bearer {recipient_token}"},
    )
    response = connection.getresponse()
    assert response.status == 200
    revoker = SeatStorage(
        server.application.settings.database_path,
        max_logical_database_bytes=server.application.settings.max_logical_database_bytes,
    )
    revoker.revoke_token(recipient_id)
    revoker.close()

    assert response.readline() == b""
    connection.close()
