"""Share configured stores and limits between concurrent HTTP handlers."""

import threading
from dataclasses import dataclass

from ovue.configuration import Settings
from ovue.seats.main import SeatStore
from ovue.storage.main import PointerStorage
from ovue.transports.http.limits import RateLimiter, StreamRegistry


@dataclass
class HTTPApplication:
    """Hold the module interfaces used by the HTTP transport."""

    settings: Settings
    pointers: PointerStorage
    seats: SeatStore
    rate_limiter: RateLimiter
    streams: StreamRegistry
    stopping: threading.Event
