"""Provide seat identity, directory, authentication, and token operations."""

from __future__ import annotations

from typing import Protocol

from ovue.configuration import Settings
from ovue.seats.entities import AuthenticatedSeat, Seat
from ovue.seats.utils import normalize_handle


class SeatStore(Protocol):
    """Describe seat persistence capabilities used by the seats boundary."""

    def create_seat(
        self,
        handle: str,
        display_name: str,
        role: str,
        *,
        max_streams_global: int | None = None,
        max_unread_global: int | None = None,
    ) -> tuple[Seat, str]: ...

    def list_seats(self) -> tuple[Seat, ...]: ...

    def known_seat_ids(self) -> set[str]: ...

    def get_seat(self, seat_id: str) -> Seat: ...

    def get_by_handle(self, handle: str) -> Seat: ...

    def rename_handle(self, seat_id: str, handle: str) -> Seat: ...

    def revoke_token(self, seat_id: str) -> None: ...

    def rotate_token(self, seat_id: str) -> str: ...

    def authenticate(self, token: str) -> AuthenticatedSeat: ...

    def is_token_active(self, seat_id: str, token: str) -> bool: ...

    def close(self) -> None: ...


def create_seat(
    storage: SeatStore,
    settings: Settings,
    *,
    handle: str,
    display_name: str,
    role: str,
) -> tuple[Seat, str]:
    """Create a normalized seat while preserving global capacity reservations."""
    return storage.create_seat(
        normalize_handle(handle),
        display_name,
        role,
        max_streams_global=settings.max_streams_global,
        max_unread_global=settings.max_unread_global,
    )


def list_seats(storage: SeatStore) -> tuple[Seat, ...]:
    """Return registered seat metadata without credential material."""
    return storage.list_seats()


def known_seat_ids(storage: SeatStore) -> set[str]:
    """Return registered seat IDs for pointer recipient validation."""
    return storage.known_seat_ids()


def get_seat(storage: SeatStore, seat_id: str) -> Seat:
    """Return one registered seat by its stable ID."""
    return storage.get_seat(seat_id)


def get_seat_by_handle(storage: SeatStore, handle: str) -> Seat:
    """Find a registered seat using its normalized human-facing handle."""
    return storage.get_by_handle(normalize_handle(handle))


def rename_seat(storage: SeatStore, seat_id: str, handle: str) -> Seat:
    """Change a seat handle while preserving its ID and bearer token."""
    return storage.rename_handle(seat_id, normalize_handle(handle))


def rotate_token(storage: SeatStore, seat_id: str) -> str:
    """Replace a seat token and invalidate its previous value immediately."""
    return storage.rotate_token(seat_id)


def revoke_token(storage: SeatStore, seat_id: str) -> None:
    """Invalidate a seat token while retaining its registered identity."""
    storage.revoke_token(seat_id)


def authenticate(storage: SeatStore, token: str) -> AuthenticatedSeat:
    """Resolve an authenticated seat from its bearer token."""
    return storage.authenticate(token)


def token_is_active(storage: SeatStore, seat_id: str, token: str) -> bool:
    """Check whether a stream's original bearer token is still valid."""
    return storage.is_token_active(seat_id, token)


def seat_directory(storage: SeatStore) -> tuple[dict[str, str], ...]:
    """Return registered seats and the operator without exposing token data."""
    registered = tuple(
        {
            "id": seat.id,
            "handle": seat.handle,
            "display_name": seat.display_name,
            "role": seat.role,
        }
        for seat in list_seats(storage)
    )
    operator = {
        "id": "operator",
        "handle": "operator",
        "display_name": "Operator",
        "role": "operator",
    }
    return (*registered, operator)
