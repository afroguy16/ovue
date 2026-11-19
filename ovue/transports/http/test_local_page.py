"""Check the local connection page keeps tokens transient and outputs safe."""

from ovue.transports.http.local_page import render_local_connection_page


def test_local_connection_page_uses_only_transient_same_origin_auth() -> None:
    """Keep tokens out of browser storage and render status using safe text."""
    page = render_local_connection_page("test-nonce").decode("utf-8")

    assert '<input id="token" name="token" type="password"' in page
    assert 'autocomplete="new-password"' in page
    assert 'fetch("/seats"' in page
    assert "Authorization: `Bearer ${token}`" in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page
    assert "document.cookie" not in page
    assert "textContent" in page
    assert 'nonce="test-nonce"' in page
