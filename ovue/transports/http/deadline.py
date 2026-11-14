"""Read one HTTP request within a single total time budget."""

from __future__ import annotations

import socket
import time
from io import BufferedReader


class DeadlineReader:
    """Apply one absolute deadline to request headers and the bounded body."""

    def __init__(
        self,
        source: BufferedReader,
        connection: socket.socket,
        timeout_seconds: float,
    ) -> None:
        """Start the request deadline before the first header byte is read."""
        self._source = source
        self._connection = connection
        self._deadline = time.monotonic() + timeout_seconds
        self._buffer = bytearray()
        self._reached_eof = False

    def readline(self, size: int = -1) -> bytes:
        """Read one protocol line without allowing slow bytes to reset the deadline."""
        maximum = size if size >= 0 else 65_537
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                return self._take(min(newline + 1, maximum))
            if len(self._buffer) >= maximum or self._reached_eof:
                return self._take(min(len(self._buffer), maximum))
            self._fill(min(8192, maximum - len(self._buffer)))

    def read(self, size: int = -1) -> bytes:
        """Read the requested body bytes under the same total request deadline."""
        if size == 0:
            return b""
        if size < 0:
            while not self._reached_eof:
                self._fill(8192)
            return self._take(len(self._buffer))
        while len(self._buffer) < size and not self._reached_eof:
            self._fill(min(8192, size - len(self._buffer)))
        return self._take(min(size, len(self._buffer)))

    def close(self) -> None:
        """Close the underlying buffered socket reader with the handler lifecycle."""
        self._source.close()

    def _fill(self, maximum: int) -> None:
        """Buffer one available chunk while respecting the original deadline."""
        chunk = self._read_chunk(maximum)
        if chunk:
            self._buffer.extend(chunk)
        else:
            self._reached_eof = True

    def _take(self, size: int) -> bytes:
        """Remove and return the requested leading bytes from the local buffer."""
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result

    def _read_chunk(self, maximum: int) -> bytes:
        """Read available bytes using the time remaining on the request deadline."""
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP request deadline exceeded")
        self._connection.settimeout(remaining)
        try:
            return self._source.read1(maximum)
        except TimeoutError:
            raise TimeoutError("HTTP request deadline exceeded") from None
