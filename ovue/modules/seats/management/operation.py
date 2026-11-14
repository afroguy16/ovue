"""Create, rename, rotate, and revoke registered seats through one boundary."""

from ovue.configuration import Settings
from ovue.modules.seats.entities import Seat
from ovue.modules.seats.storage.sqlite import SeatStorage


def create_seat(
    storage: SeatStorage,
    settings: Settings,
    *,
    handle: str,
    display_name: str,
    role: str,
) -> tuple[Seat, str]:
    """Atomically reserve global capacity before registering and tokenizing a seat."""
    return storage.create_seat(
        handle,
        display_name,
        role,
        max_streams_global=settings.max_streams_global,
        max_unread_global=settings.max_unread_global,
    )


def rename_seat(storage: SeatStorage, seat_id: str, handle: str) -> Seat:
    """Change the seat's human-readable handle while preserving its ID."""
    return storage.rename_handle(seat_id, handle)


def rotate_token(storage: SeatStorage, seat_id: str) -> str:
    """Issue a replacement token and invalidate the prior one immediately."""
    return storage.rotate_token(seat_id)


def revoke_token(storage: SeatStorage, seat_id: str) -> None:
    """Invalidate a token while keeping its seat available for later rotation."""
    storage.revoke_token(seat_id)
