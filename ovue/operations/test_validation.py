"""Check pointer details against the contract without sending or saving them."""

from dataclasses import replace

import pytest

from ovue.operations.validation import (
    IssueRejected,
    Payload,
    Policy,
    validate,
)


def make_payload() -> Payload:
    """Make valid pointer details for the validation tests."""
    return Payload(
        to=("seat_b",),
        ref_url="https://work.example.org/items/42",
        ref_title="CT-2",
        description="Ready for review",
        kind="done",
    )


def make_policy(*, local_deployment: bool = False) -> Policy:
    """Allow one web address host and set limits for storage and inbox size."""
    return Policy(
        allowed_hosts=frozenset({"work.example.org"}),
        max_pointer_records=10,
        max_logical_database_bytes=1_000_000,
        max_unread_per_seat=2,
        local_deployment=local_deployment,
    )


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


def test_validation_accepts_ten_distinct_recipients() -> None:
    """Allow the full recipient count permitted by the pointer contract."""
    recipients = tuple(f"seat_{index}" for index in range(10))

    accepted = validate(
        replace(make_payload(), to=recipients),
        sender_id="sender",
        known_seat_ids=set(recipients),
        policy=make_policy(),
    )

    assert accepted == recipients


def test_validation_accepts_twelve_character_title_and_reports_its_limit() -> None:
    """Allow a title at twelve characters and attach the limit to a rejection."""
    payload = replace(make_payload(), ref_title="x" * 12)
    assert validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
    ) == ("seat_b",)

    with pytest.raises(IssueRejected) as error:
        validate(
            replace(payload, ref_title="x" * 13),
            sender_id="seat_a",
            known_seat_ids={"seat_a", "seat_b"},
            policy=make_policy(),
        )

    issue = next(
        issue for issue in error.value.issues if issue.path == ("ref", "title")
    )
    assert issue.code == "too_long"
    assert issue.max_value == 12


def test_validation_accepts_url_at_2048_characters() -> None:
    """Allow an absolute reference URL that uses the full configured limit."""
    prefix = "https://work.example.org/"
    payload = replace(make_payload(), ref_url=prefix + "a" * (2048 - len(prefix)))

    assert validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
    ) == ("seat_b",)


@pytest.mark.parametrize(
    ("url", "expected_code"),
    [
        ("https://user:secret@work.example.org/items/42", "userinfo_not_allowed"),
        ("https://127.0.0.1/items/42", "invalid_host"),
        ("https://work.example.org./items/42", "invalid_host"),
        ("https://xn--bcher-kva.example/items/42", "invalid_host"),
        ("https://work.example.org:8443/items/42", "non_default_port"),
    ],
)
def test_validation_rejects_unsafe_reference_url_shapes(
    url: str,
    expected_code: str,
) -> None:
    """Reject URL forms that can confuse host validation or safe navigation."""
    with pytest.raises(IssueRejected) as error:
        validate(
            replace(make_payload(), ref_url=url),
            sender_id="seat_a",
            known_seat_ids={"seat_a", "seat_b"},
            policy=make_policy(),
        )

    assert expected_code in {issue.code for issue in error.value.issues}


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
            replace(make_payload(), ref_url="data:text/html,example"),
            "seat_a",
            {"seat_a", "seat_b"},
            "invalid_scheme",
        ),
        (
            replace(make_payload(), ref_url="file:///tmp/example"),
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
            replace(make_payload(), ref_url="https://work.example.org/item?"),
            "seat_a",
            {"seat_a", "seat_b"},
            "query_or_fragment_not_allowed",
        ),
        (
            replace(make_payload(), ref_url="https://work.example.org/item#"),
            "seat_a",
            {"seat_a", "seat_b"},
            "query_or_fragment_not_allowed",
        ),
        (
            replace(make_payload(), ref_url="https://work.example.org/a\nb"),
            "seat_a",
            {"seat_a", "seat_b"},
            "invalid_url",
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


def test_validation_accepts_description_at_120_characters() -> None:
    """Allow a description that uses all 120 permitted characters."""
    recipients = validate(
        replace(make_payload(), description="x" * 120),
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=make_policy(),
    )

    assert recipients == ("seat_b",)


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


def test_validation_allows_https_localhost_with_an_empty_local_allowlist() -> None:
    """Allow localhost references in local mode without a configured host entry."""
    payload = replace(make_payload(), ref_url="https://localhost/items/42")
    policy = replace(make_policy(local_deployment=True), allowed_hosts=frozenset())

    recipients = validate(
        payload,
        sender_id="seat_a",
        known_seat_ids={"seat_a", "seat_b"},
        policy=policy,
    )

    assert recipients == ("seat_b",)
