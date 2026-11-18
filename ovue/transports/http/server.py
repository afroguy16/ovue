"""Create and run the configured Ovue HTTP and SSE service."""

from __future__ import annotations

import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ovue.configuration import ConfigurationError, Settings
from ovue.operations.main import warn_if_near_capacity
from ovue.seats.main import list_seats
from ovue.storage.main import SQLite
from ovue.storage.seats import SeatStorage
from ovue.transports.http.application import HTTPApplication
from ovue.transports.http.limits import RateLimiter, StreamRegistry
from ovue.transports.http.main import OvueRequestHandler

_Request = socket.socket | tuple[bytes, socket.socket]


class OvueHTTPServer(ThreadingHTTPServer):
    """Serve requests concurrently and share the configured module interfaces."""

    daemon_threads = False
    allow_reuse_address = True
    application: HTTPApplication

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        application: HTTPApplication,
    ) -> None:
        """Create a server with no more request workers than configured."""
        super().__init__(address, handler)
        self.application = application
        self._request_slots = threading.BoundedSemaphore(
            application.settings.max_http_workers
        )

    def process_request(
        self,
        request: _Request,
        client_address: tuple[str, int],
    ) -> None:
        """Reject excess connections before they can create unbounded threads."""
        if not self._request_slots.acquire(blocking=False):
            self._reject_busy_request(request)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(
        self,
        request: _Request,
        client_address: tuple[str, int],
    ) -> None:
        """Release the worker slot after the request or stream has ended."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def _reject_busy_request(self, request: _Request) -> None:
        """Return a small JSON overload response without starting a worker."""
        response = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: 23\r\n"
            b"Connection: close\r\n\r\n"
            b'{"error":"server_busy"}'
        )
        try:
            connection = request[1] if isinstance(request, tuple) else request
            connection.sendall(response)
        except OSError:
            pass

    def shutdown(self) -> None:
        """Stop active SSE loops before stopping the request-accept loop."""
        self.application.stopping.set()
        super().shutdown()


def create_server(settings: Settings) -> OvueHTTPServer:
    """Open protected stores and construct a local or TLS-protected server."""
    settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    seats = SeatStorage(
        settings.database_path,
        max_logical_database_bytes=settings.max_logical_database_bytes,
    )
    try:
        registered_count = len(list_seats(seats))
        if settings.max_streams_global < registered_count:
            raise ConfigurationError(
                "Global stream capacity is below registered seat reservations"
            )
        if settings.max_unread_global < registered_count * 10:
            raise ConfigurationError(
                "Global unread capacity is below registered seat reservations"
            )
        pointers = SQLite(
            settings.database_path,
            max_logical_database_bytes=settings.max_logical_database_bytes,
        )
    except Exception:
        seats.close()
        raise
    warn_if_near_capacity(
        pointers,
        max_pointer_records=settings.max_pointer_records,
        max_logical_database_bytes=settings.max_logical_database_bytes,
    )
    application = HTTPApplication(
        settings=settings,
        pointers=pointers,
        seats=seats,
        rate_limiter=RateLimiter(),
        streams=StreamRegistry(
            per_seat_limit=settings.max_streams_per_seat,
            global_limit=settings.max_streams_global,
        ),
        stopping=threading.Event(),
    )
    server: OvueHTTPServer | None = None
    try:
        server = OvueHTTPServer(
            (settings.host, settings.port),
            OvueRequestHandler,
            application,
        )
        if settings.tls_certfile is not None and settings.tls_keyfile is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(settings.tls_certfile, settings.tls_keyfile)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        return server
    except Exception:
        if server is not None:
            server.server_close()
        pointers.close()
        seats.close()
        raise


def serve(settings: Settings) -> None:
    """Run the service until interrupted, then close its sockets and stores."""
    server = create_server(settings)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.application.stopping.set()
        server.server_close()
        server.application.pointers.close()
        server.application.seats.close()
