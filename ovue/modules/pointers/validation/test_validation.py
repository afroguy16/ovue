"""Test pointer contract validation independently from send and storage."""

from dataclasses import replace

import pytest

from ovue.modules.pointers.validation.validation import (
    IssueRejected,
    Payload,
    Policy,
    validate,
)


def make_payload() -> Payload:
    """Return a valid payload for focused validation cases."""
    return Payload(
        to=("seat_b",),
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )


def make_policy(*, local_deployment: bool = False) -> Policy:
    """Allow one reference host and use finite capacity values."""
    return Policy(
        allowed_hosts=frozenset({"work.example.org"}),
        max_pointer_records=10,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
        local_deployment=local_deployment,
    )


def test_validation_deduplicates_recipients_preserving_order() -> None:
    """Duplicate IDs collapse after the submitted list passes its size limit."""
    payload = replace(make_payload(), to=("seat_c", "seat_b", "seat_c"))

    recipients = validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
        policy=make_policy(),
    )

    assert recipients == ("seat_c", "seat_b")


@pytest.mark.parametrize(
    ("payload", "sender_id", "known_seat_ids", "expected_code"),
    [
        (replace(make_payload(), to=()), "seat_a", {"seat_a"}, "required"),
        (
            replace(make_payload(), to=("seat_a",)),
            "seat_a",
            {"seat_a"},
            "sender_is_recipient",
        ),
        (
            replace(make_payload(), to=("unknown",)),
            "seat_a",
            {"seat_a"},
            "unknown_seat_id",
        ),
        (
            replace(make_payload(), to=tuple(f"s{i}" for i in range(11))),
            "sender",
            {"sender", *(f"s{i}" for i in range(11))},
            "too_many_recipients",
        ),
        (
            replace(make_payload(), ref_url="javascript:alert(1)"),
            "seat_a",
            {"seat_a", "seat_b"},
            "invalid_scheme",
        ),
        (
            replace(make_payload(), ref_url="https://outside.example/item"),
            "seat_a",
            {"seat_a", "seat_b"},
            "host_not_allowed",
        ),
        (
            replace(make_payload(), ref_title="bad!"),
            "seat_a",
            {"seat_a", "seat_b"},
            "invalid_characters",
        ),
        (
            replace(make_payload(), description="line\nbreak"),
            "seat_a",
            {"seat_a", "seat_b"},
            "invalid_characters",
        ),
        (
            replace(make_payload(), kind="chat"),
            "seat_a",
            {"seat_a", "seat_b"},
            "unsupported_kind",
        ),
    ],
)
def test_validation_rejects_invalid_payloads(
    payload: Payload,
    sender_id: str,
    known_seat_ids: set[str],
    expected_code: str,
) -> None:
    """Invalid submissions report the expected issue code without submitted text."""
    with pytest.raises(IssueRejected) as error:
        validate(
            payload,
            sender_id=sender_id,
            known_seat_ids=known_seat_ids,
            policy=make_policy(),
        )

    assert any(issue.code == expected_code for issue in error.value.issues)


def test_validation_accepts_description_at_120_characters() -> None:
    """A description at its inclusive maximum remains valid."""
    recipients = validate(
        replace(make_payload(), description="x" * 120),
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
    )

    assert recipients == ("seat_b",)


def test_validation_allows_http_localhost_only_for_local_deployment() -> None:
    """Local HTTP references are allowed only when local mode is enabled."""
    payload = replace(make_payload(), ref_url="http://localhost/items/42")

    recipients = validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(local_deployment=True),
    )

    assert recipients == ("seat_b",)
