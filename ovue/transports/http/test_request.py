"""Check safe parsing of pointer JSON into the transport-neutral contract."""

import pytest

from ovue.modules.pointers.validation.validation import IssueRejected
from ovue.transports.http.request import parse_pointer_payload


def test_parse_pointer_payload_returns_typed_pointer_fields() -> None:
    """Read only the fields in the pointer contract and preserve recipient order."""
    payload = parse_pointer_payload(
        {
            "to": ["seat_b", "seat_c"],
            "ref": {"url": "https://work.example.org/i/1", "title": "CT-2"},
            "description": "Ready",
            "kind": "done",
        }
    )

    assert payload.to == ("seat_b", "seat_c")
    assert payload.ref_title == "CT-2"
    assert payload.description == "Ready"


def test_parse_pointer_payload_rejects_sender_and_collects_missing_fields() -> None:
    """Reject a body-supplied sender and report other shape issues without values."""
    with pytest.raises(IssueRejected) as error:
        parse_pointer_payload({"from": "seat_a", "to": "seat_b", "ref": {}})

    issues = error.value.issues
    assert {issue.path for issue in issues} >= {
        ("from",),
        ("to",),
        ("ref", "url"),
        ("description",),
        ("kind",),
    }
    assert "seat_a" not in str(error.value)
