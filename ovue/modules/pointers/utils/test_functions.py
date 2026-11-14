"""Check the small helper functions that examine pointer details."""

from ovue.modules.pointers.utils.functions import (
    is_printable_ascii,
    split_url,
    unique_in_order,
)


def test_unique_in_order_removes_duplicates_without_reordering() -> None:
    """Remove repeated values while keeping the first one's position."""
    assert unique_in_order(("seat_b", "seat_a", "seat_b")) == (
        "seat_b",
        "seat_a",
    )


def test_split_url_returns_parts_for_valid_url() -> None:
    """Return the scheme, host, and path from a valid web address."""
    parts = split_url("https://work.example.org/items/42")

    assert parts is not None
    assert parts.scheme == "https"
    assert parts.hostname == "work.example.org"
    assert parts.path == "/items/42"


def test_split_url_returns_none_for_malformed_url() -> None:
    """Return no result for an invalid web address instead of raising an error."""
    assert split_url("https://[invalid") is None


def test_is_printable_ascii_accepts_visible_characters() -> None:
    """Allow visible standard keyboard characters in a description."""
    assert is_printable_ascii("Ready for review ~")


def test_is_printable_ascii_rejects_controls_and_non_ascii() -> None:
    """Reject line breaks and characters outside standard ASCII."""
    assert not is_printable_ascii("Ready\nfor review")
    assert not is_printable_ascii("Naira ₦")
