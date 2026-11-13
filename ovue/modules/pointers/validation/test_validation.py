"""Check pointer details against the contract without sending or saving them."""

from dataclasses import replace

import pytest

from ovue.modules.pointers.validation.validation import (
    IssueRejected,
    Payload,
    Policy,
    validate,
)


# Start with valid pointer details so each test changes only what it checks.
def make_payload() -> Payload:
    """Make valid pointer details for the validation tests."""
    return Payload(
        to=("seat_b",),
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )


# Use the same allowed host and capacity limits in each validation test.
def make_policy(*, local_deployment: bool = False) -> Policy:
    """Allow one web address host and set limits for storage and inbox size."""
    return Policy(
        allowed_hosts=frozenset({"work.example.org"}),
        max_pointer_records=10,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
        local_deployment=local_deployment,
    )


# Keep each seat once, in the order it first appears in the recipient list.
def test_validation_deduplicates_recipients_preserving_order() -> None:
    """Keep only the first occurrence of each seat ID in the recipient list."""
    payload = replace(make_payload(), to=("seat_c", "seat_b", "seat_c"))

    recipients = validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b", "seat_c"},
        policy=make_policy(),
    )

    assert recipients == ("seat_c", "seat_b")


# Check that each kind of invalid pointer detail reports the right problem.
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
    """Report the right problem without repeating the submitted text."""
    with pytest.raises(IssueRejected) as error:
        validate(
            payload,
            sender_id=sender_id,
            known_seat_ids=known_seat_ids,
            policy=make_policy(),
        )

    # Validation may report several problems, so check whether one matches.
    assert any(issue.code == expected_code for issue in error.value.issues)


# Check that a description with exactly 120 characters is allowed.
def test_validation_accepts_description_at_120_characters() -> None:
    """Allow a description that uses all 120 permitted characters."""
    recipients = validate(
        replace(make_payload(), description="x" * 120),
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
    )

    assert recipients == ("seat_b",)


# Reject a description as soon as it exceeds the 120-character limit.
def test_validation_rejects_description_at_121_characters() -> None:
    """Report a length problem when a description has 121 characters."""
    with pytest.raises(IssueRejected) as error:
        validate(
            replace(make_payload(), description="x" * 121),
            sender_id="seat_a",
            known_seat_ids={"seat_a", "seat_b"},
            policy=make_policy(),
        )

    assert any(
        issue.code == "too_long" and issue.path == ("description",)
        for issue in error.value.issues
    )


# Allow a localhost web address only when the service is in local mode.
def test_validation_allows_http_localhost_only_for_local_deployment() -> None:
    """Allow an unencrypted localhost address only in local mode."""
    payload = replace(make_payload(), ref_url="http://localhost/items/42")

    recipients = validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(local_deployment=True),
    )

    assert recipients == ("seat_b",)
