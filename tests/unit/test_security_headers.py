from flask import Response

from notes_app.interfaces.http.security import (
    CONTENT_SECURITY_POLICY,
    HARDENED_COOKIE,
    SESSION_COOKIE,
    apply_security_headers,
    clear_session_cookie,
    set_session_cookie,
)


def test_the_content_security_policy_allows_no_script_and_no_framing():
    directives = dict(part.strip().split(" ", 1) for part in CONTENT_SECURITY_POLICY.split(";"))
    assert directives["default-src"] == "'none'"
    assert "script-src" not in directives  # falls back to default-src 'none'
    assert directives["frame-ancestors"] == "'none'"
    assert directives["base-uri"] == "'none'"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY


def test_headers_are_added_but_a_handlers_own_value_wins():
    response = Response("x")
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    apply_security_headers(response)
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY


def test_the_session_cookie_is_host_prefixed_http_only_secure_and_same_site():
    response = Response("x")
    set_session_cookie(response, "opaque", 900, HARDENED_COOKIE)
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=opaque")
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=900"):
        assert attribute in cookie
    assert "Domain" not in cookie


def test_clearing_the_cookie_expires_it_with_the_same_attributes():
    response = Response("x")
    clear_session_cookie(response, HARDENED_COOKIE)
    cookie = response.headers["Set-Cookie"]
    assert "Max-Age=0" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
