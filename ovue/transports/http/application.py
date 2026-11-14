"""Share configured stores and limits between concurrent HTTP handlers."""

import threading
from dataclasses import dataclass

from ovue.configuration import Settings
from ovue.modules.pointers.storage.sqlite import SQLite
from ovue.modules.seats.storage.sqlite import SeatStorage
from ovue.transports.http.limits import RateLimiter, StreamRegistry


@dataclass
class HTTPApplication:
    """Hold the module interfaces used by the HTTP transport."""

    settings: Settings
    pointers: SQLite
    seats: SeatStorage
    rate_limiter: RateLimiter
    streams: StreamRegistry
    stopping: threading.Event
