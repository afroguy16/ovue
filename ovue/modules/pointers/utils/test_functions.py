"""Test the pure helper functions used by pointer validation."""

from ovue.modules.pointers.utils.functions import (
    is_printable_ascii,
    split_url,
    unique_in_order,
)


def test_unique_in_order_removes_duplicates_without_reordering() -> None:
    """Duplicate recipients collapse while first-seen order is retained."""
    assert unique_in_order(("seat_b", "seat_a", "seat_b")) == (
        "seat_b",
        "seat_a",
    )


def test_split_url_returns_parts_for_valid_url() -> None:
    """A valid URL is returned as its standard parsed components."""
    parts = split_url("https://work.example.org/items/42")

    assert parts is not None
    assert parts.scheme == "https"
    assert parts.hostname == "work.example.org"
    assert parts.path == "/items/42"


def test_split_url_returns_none_for_malformed_url() -> None:
    """Malformed URL syntax is represented without leaking parser exceptions."""
    assert split_url("https://[invalid") is None


def test_is_printable_ascii_accepts_visible_characters() -> None:
    """Printable ASCII descriptions pass the character check."""
    assert is_printable_ascii("Ready for review ~")


def test_is_printable_ascii_rejects_controls_and_non_ascii() -> None:
    """Control characters and non-ASCII text fail the character check."""
    assert not is_printable_ascii("Ready\nfor review")
    assert not is_printable_ascii("Naira ₦")
