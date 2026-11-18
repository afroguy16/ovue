"""Build the authenticated seat directory response."""

from ovue.storage.seats import SeatStorage


def seat_directory(storage: SeatStorage) -> tuple[dict[str, str], ...]:
    """Return registered seats and the reserved Founder identity without tokens."""
    registered = tuple(
        {
            "id": seat.id,
            "handle": seat.handle,
            "display_name": seat.display_name,
            "role": seat.role,
        }
        for seat in storage.list_seats()
    )
    operator = {
        "id": "operator",
        "handle": "founder",
        "display_name": "Founder",
        "role": "operator",
    }
    return (*registered, operator)
