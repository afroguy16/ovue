"""Check total request deadlines against peers that drip bytes slowly."""

import socket
import threading
import time

import pytest

from ovue.transports.http.deadline import DeadlineReader


def test_header_deadline_does_not_restart_when_more_bytes_arrive() -> None:
    """Stop a request even when each byte arrives before the socket idle timeout."""
    server_socket, client_socket = socket.socketpair()
    source = server_socket.makefile("rb")
    reader = DeadlineReader(source, server_socket, timeout_seconds=0.15)

    def send_slow_header() -> None:
        for byte in (b"G", b"E", b"T", b"\n"):
            try:
                client_socket.sendall(byte)
            except OSError:
                return
            time.sleep(0.06)

    sender = threading.Thread(target=send_slow_header)
    sender.start()
    try:
        with pytest.raises(TimeoutError, match="deadline exceeded"):
            reader.readline()
    finally:
        client_socket.close()
        source.close()
        server_socket.close()
        sender.join(timeout=1)


def test_body_deadline_does_not_restart_when_more_bytes_arrive() -> None:
    """Apply the same absolute deadline while reading a request body."""
    server_socket, client_socket = socket.socketpair()
    source = server_socket.makefile("rb")
    reader = DeadlineReader(source, server_socket, timeout_seconds=0.15)

    def send_slow_body() -> None:
        for byte in (b"a", b"b", b"c", b"d"):
            try:
                client_socket.sendall(byte)
            except OSError:
                return
            time.sleep(0.06)

    sender = threading.Thread(target=send_slow_body)
    sender.start()
    try:
        with pytest.raises(TimeoutError, match="deadline exceeded"):
            reader.read(4)
    finally:
        client_socket.close()
        source.close()
        server_socket.close()
        sender.join(timeout=1)
