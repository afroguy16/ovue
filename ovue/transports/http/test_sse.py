"""Check event framing and heartbeat comments used by the HTTP stream."""

import json

from ovue.transports.http.sse import encode_event, heartbeat


def test_sse_event_has_sequence_id_and_one_json_data_line() -> None:
    """Keep each pointer event consumable as one compact JSON line."""
    event = {
        "event_id": 12,
        "delivery_id": "delivery-1",
        "description": "Ready",
    }

    lines = encode_event(event).decode("ascii").splitlines()

    assert lines[0] == "id: 12"
    assert json.loads(lines[1].removeprefix("data: ")) == event
    assert len(lines) == 3
    assert lines[2] == ""


def test_heartbeat_is_a_comment_and_not_a_message_event() -> None:
    """Use an SSE comment frame to keep an idle connection alive."""
    assert heartbeat() == b": keep-alive\n\n"
