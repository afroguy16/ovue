"""Check the format and reserved-name rules for seat handles."""

import pytest

from ovue.modules.seats.handles.validation import normalize_handle


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [("Writer-1", "writer-1"), ("a_b", "a_b"), ("SEAT9", "seat9")],
)
def test_normalize_handle_accepts_valid_ascii_handles(
    submitted: str,
    expected: str,
) -> None:
    """Accept valid handles and normalize their letters to lowercase."""
    assert normalize_handle(submitted) == expected


@pytest.mark.parametrize(
    "submitted",
    ["a", "_seat", "-seat", "has space", "has.dot", "founder", "FOUNDER", "x" * 33],
)
def test_normalize_handle_rejects_invalid_or_reserved_values(submitted: str) -> None:
    """Reject malformed handles and the reserved operator handle."""
    with pytest.raises(ValueError):
        normalize_handle(submitted)
