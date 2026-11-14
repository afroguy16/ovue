"""Create and run the configured Ovue HTTP and SSE service."""

from __future__ import annotations

import ssl
import threading
from http.server import ThreadingHTTPServer

from ovue.configuration import ConfigurationError, Settings
from ovue.modules.pointers.monitoring.operation import warn_if_near_capacity
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.seats.storage.sqlite import SeatStorage
from ovue.transports.http.application import HTTPApplication
from ovue.transports.http.handler import OvueRequestHandler
from ovue.transports.http.limits import RateLimiter, StreamRegistry


class OvueHTTPServer(ThreadingHTTPServer):
    """Serve requests concurrently and share the configured module interfaces."""

    daemon_threads = False
    allow_reuse_address = True
    application: HTTPApplication

    def shutdown(self) -> None:
        """Stop active SSE loops before stopping the request-accept loop."""
        self.application.stopping.set()
        super().shutdown()


def create_server(settings: Settings) -> OvueHTTPServer:
    """Open protected stores and construct a local or TLS-protected server."""
    settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    seats = SeatStorage(settings.database_path)
    try:
        registered_count = len(seats.list_seats())
        if settings.max_streams_global < registered_count:
            raise ConfigurationError(
                "Global stream capacity is below registered seat reservations"
            )
        if settings.max_unread_global < registered_count * 10:
            raise ConfigurationError(
                "Global unread capacity is below registered seat reservations"
            )
        pointers = SQLite(settings.database_path)
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
        server = OvueHTTPServer((settings.host, settings.port), OvueRequestHandler)
        server.application = application
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
