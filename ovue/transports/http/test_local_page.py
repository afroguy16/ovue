"""Check the local connection page keeps tokens transient and outputs safe."""

from ovue.transports.http.local_page import render_local_page


def test_local_page_offers_worker_inbox_and_operator_traffic_views() -> None:
    """Keep both roles' credentials transient and render pointer fields safely."""
    page = render_local_page("test-nonce").decode("utf-8")

    assert '<input id="token" name="token" type="password"' in page
    assert 'autocomplete="new-password"' in page
    assert 'fetch("/me"' in page
    assert "headers: { Authorization: workerAuthorization }" in page
    assert 'id="operator-code"' in page
    assert 'fetch("/operator/session"' in page
    assert "fetch(`/operator/traffic?${query}`" in page
    assert "encodeURIComponent(workerSeatId)" in page
    assert 'query.set("unread", "1")' in page
    assert 'query.set("cursor", workerCursor)' in page
    assert "encodeURIComponent(record.delivery_id)" in page
    assert "Refresh inbox" in page
    assert "Refresh traffic" in page
    assert "Load older traffic" in page
    assert 'query.set("cursor", operatorCursor)' in page
    assert 'credentials: "same-origin"' in page
    assert "operatorAuthorization" not in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page
    assert "document.cookie" not in page
    assert "textContent" in page
    assert 'nonce="test-nonce"' in page
