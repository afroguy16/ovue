"""Manage the short-lived operator credential used by the local browser view."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time


class OperatorAccess:
    """Exchange one startup code for one temporary in-memory browser session."""

    _CODE_LIFETIME_SECONDS = 5 * 60
    _SESSION_LIFETIME_SECONDS = 8 * 60 * 60

    def __init__(self, code: str, *, now: float) -> None:
        """Keep credential hashes and expiry times without retaining raw secrets."""
        self._lock = threading.Lock()
        self._code_hash: bytes | None = self._digest(code)
        self._code_expires_at = now + self._CODE_LIFETIME_SECONDS
        self._session_hash: bytes | None = None
        self._session_expires_at = 0.0

    @classmethod
    def create(cls) -> tuple[OperatorAccess, str]:
        """Create an access manager and return its one-time terminal code."""
        code = secrets.token_urlsafe(32)
        return cls(code, now=time.monotonic()), code

    def exchange(self, code: str) -> str | None:
        """Consume the valid bootstrap code and issue a random browser token."""
        submitted_hash = self._digest(code)
        with self._lock:
            if self._code_hash is None or time.monotonic() >= self._code_expires_at:
                self._code_hash = None
                return None
            if not hmac.compare_digest(submitted_hash, self._code_hash):
                return None
            self._code_hash = None
            session = secrets.token_urlsafe(32)
            self._session_hash = self._digest(session)
            self._session_expires_at = time.monotonic() + self._SESSION_LIFETIME_SECONDS
            return session

    def authorizes(self, token: str) -> bool:
        """Check a browser token without exposing its stored hash or expiry."""
        submitted_hash = self._digest(token)
        with self._lock:
            if (
                self._session_hash is None
                or time.monotonic() >= self._session_expires_at
            ):
                self._session_hash = None
                return False
            return hmac.compare_digest(submitted_hash, self._session_hash)

    @staticmethod
    def _digest(secret: str) -> bytes:
        """Hash a credential before comparing or retaining it."""
        return hashlib.sha256(secret.encode("utf-8")).digest()
