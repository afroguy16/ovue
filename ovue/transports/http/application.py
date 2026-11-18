"""Share configured stores and limits between concurrent HTTP handlers."""

import threading
from dataclasses import dataclass

from ovue.configuration import Settings
from ovue.storage.main import PointerStorage
from ovue.storage.seats import SeatStorage
from ovue.transports.http.limits import RateLimiter, StreamRegistry


@dataclass
class HTTPApplication:
    """Hold the module interfaces used by the HTTP transport."""

    settings: Settings
    pointers: PointerStorage
    seats: SeatStorage
    rate_limiter: RateLimiter
    streams: StreamRegistry
    stopping: threading.Event
