"""Define the public identity data returned by the seats module."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    """Describe a registered seat without exposing any credential material."""

    id: str
    handle: str
    display_name: str
    role: str
    token_active: bool


@dataclass(frozen=True)
class AuthenticatedSeat:
    """Identify the seat resolved from a valid bearer token."""

    id: str
    handle: str
    display_name: str
    role: str
