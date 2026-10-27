"""Browser-facing defenses: response headers, the session cookie's attributes and the CSRF rule."""

from __future__ import annotations

from dataclasses import dataclass

from flask import Response

SESSION_COOKIE = "__Host-session"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# A page that runs no script and loads only its own stylesheet; it cannot be framed, cannot change its base URL
# and can post forms only to itself. A stored-XSS bug would still find nothing to run.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


def apply_security_headers(response: Response) -> Response:
    """Add the security headers to every response; a handler's own value wins."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@dataclass(frozen=True, slots=True)
class CookieAttributes:
    """The attributes of the session cookie."""

    http_only: bool
    secure: bool
    same_site: str | None


HARDENED_COOKIE = CookieAttributes(http_only=True, secure=True, same_site="Lax")
WEAK_COOKIE = CookieAttributes(http_only=False, secure=False, same_site=None)  # UNSAFE_WEAK_SESSION_COOKIE


def set_session_cookie(response: Response, raw_token: str, max_age: int, attributes: CookieAttributes) -> None:
    """Attach the opaque session id. The ``__Host-`` prefix makes browsers insist on Secure, Path=/ and no Domain."""
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=max_age,
        httponly=attributes.http_only,
        secure=attributes.secure,
        samesite=attributes.same_site,
        path="/",
    )


def clear_session_cookie(response: Response, attributes: CookieAttributes) -> None:
    """Expire the cookie in the browser."""
    response.delete_cookie(
        SESSION_COOKIE, httponly=attributes.http_only, secure=attributes.secure, samesite=attributes.same_site, path="/"
    )
