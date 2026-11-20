"""Check one-time operator codes and temporary browser sessions."""

import time

from ovue.transports.http.operator_access import OperatorAccess


def test_operator_code_can_be_exchanged_once_for_a_temporary_session() -> None:
    """Allow one browser session from the local operator's one-time code."""
    access, code = OperatorAccess.create()

    session = access.exchange(code)

    assert session is not None
    assert access.authorizes(session)
    assert access.exchange(code) is None
    assert not access.authorizes(code)


def test_operator_code_expires_before_exchange() -> None:
    """Reject a code after its short bootstrap window has elapsed."""
    access, code = OperatorAccess.create()
    access._code_expires_at = time.monotonic() - 1

    assert access.exchange(code) is None


def test_operator_session_expires_after_its_lifetime() -> None:
    """Reject the in-memory session after its configured lifetime."""
    access, code = OperatorAccess.create()
    session = access.exchange(code)
    assert session is not None
    access._session_expires_at = time.monotonic() - 1

    assert not access.authorizes(session)
