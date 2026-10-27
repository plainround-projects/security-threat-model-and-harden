"""``notes-app-demo``: the lesson's scenario against a running server, printed as checked steps.

It signs up generated users (passwords are random and never printed), then shows each control from the threat
model working: cookie flags, headers, output encoding, authorization, CSRF, throttling, sign-out.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

from notes_app.interfaces.http.security import CSRF_HEADER, SESSION_COOKIE

HOSTILE = "<script>alert(1)</script> and a quote: ' OR '1'='1"
_CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
REQUIRED_HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options")


@dataclass(frozen=True, slots=True)
class Step:
    """One checked claim of the scenario."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Reply:
    """The parts of an HTTP response the scenario looks at."""

    status: int
    headers: dict[str, str]
    set_cookies: tuple[str, ...]
    body: str

    def json(self) -> dict[str, object]:
        """The body as a JSON object."""
        parsed = json.loads(self.body)
        return parsed if isinstance(parsed, dict) else {}


class Browser:
    """A tiny HTTP client with one cookie. It sets the Secure cookie by hand because plain-http clients rightly
    refuse to send it; a real browser treats http://localhost as secure."""

    def __init__(self, host: str, port: int) -> None:
        self._host, self._port = host, port
        self.cookie: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        form: dict[str, str] | None = None,
        body: object = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        """Send one request and remember a cookie the server sets or clears."""
        sent = dict(headers or {})
        payload: str | None = None
        if form is not None:
            payload = urlencode(form)
            sent["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            payload = json.dumps(body)
            sent["Content-Type"] = "application/json"
            sent["Accept"] = "application/json"
        if self.cookie:
            sent["Cookie"] = f"{SESSION_COOKIE}={self.cookie}"
        connection = http.client.HTTPConnection(self._host, self._port, timeout=10)
        try:
            connection.request(method, path, body=payload, headers=sent)
            response = connection.getresponse()
            text = response.read().decode()
            cookies = tuple(value for name, value in response.getheaders() if name.lower() == "set-cookie")
            reply = Reply(response.status, dict(response.getheaders()), cookies, text)
        finally:
            connection.close()
        for header in reply.set_cookies:
            name, _, rest = header.partition("=")
            if name == SESSION_COOKIE:
                self.cookie = None if "Max-Age=0" in header else rest.split(";", 1)[0]
        return reply

    def csrf_token(self) -> str:
        """The current session's CSRF token, read from the sign-in form."""
        match = _CSRF_FIELD.search(self.request("GET", "/login").body)
        if match is None:
            raise RuntimeError("no CSRF token on the sign-in page")
        return match.group(1)

    def register(self, prefix: str) -> tuple[str, str, Reply]:
        """Sign up and sign in a new generated user; returns the username, the password and the sign-in reply."""
        username, password = f"{prefix}_{secrets.token_hex(4)}", secrets.token_urlsafe(18)
        self.request(
            "POST", "/signup", form={"username": username, "password": password, "csrf_token": self.csrf_token()}
        )
        signed_in = self.request(
            "POST", "/login", form={"username": username, "password": password, "csrf_token": self.csrf_token()}
        )
        return username, password, signed_in

    def api(self, method: str, path: str, body: object = None, *, csrf: str | None = "auto") -> Reply:
        """A JSON request with the session's CSRF token (``"auto"``), none (``None``) or a given one."""
        token = self.csrf_token() if csrf == "auto" else csrf
        return self.request(method, path, body=body, headers={CSRF_HEADER: token} if token else {})


def _cookie_flags(set_cookies: tuple[str, ...]) -> tuple[bool, str]:
    cookie = next((value for value in set_cookies if value.startswith(f"{SESSION_COOKIE}=")), "")
    value = cookie.split("=", 1)[1].split(";", 1)[0] if cookie else ""
    flags = all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"))
    opaque = len(value) >= 40 and value.count(".") < 2
    return flags and opaque, f"{cookie.split(';', 1)[0][:24]}... ({len(value)} chars) " + "; ".join(
        part.strip() for part in cookie.split(";")[1:]
    )


def run_scenario(host: str, port: int) -> list[Step]:
    """Run every step against the server and return the results. Never raises on a failed expectation."""
    alice, bob, steps = Browser(host, port), Browser(host, port), []

    def check(name: str, passed: bool, detail: str) -> None:
        steps.append(Step(name, passed, detail))

    ready = alice.request("GET", "/readyz")
    check("the server is ready", ready.status == 200, f"/readyz -> {ready.status}")

    _, _, signed_in = alice.register("alice")
    bob_name, bob_password, _ = bob.register("bob")
    ok, detail = _cookie_flags(signed_in.set_cookies)
    check("the session cookie is opaque, HttpOnly, Secure, SameSite=Lax", ok, detail)

    page = alice.request("GET", "/notes")
    missing = [name for name in REQUIRED_HEADERS if name not in page.headers]
    check("security headers are on the response", not missing, f"missing: {missing or 'none'}")

    created = alice.api("POST", "/notes", {"title": "It's a title", "content": HOSTILE})
    note_id = int(str(created.json().get("id", 0)))
    note_page = alice.request("GET", f"/notes/{note_id}").body
    check(
        "hostile content is stored and rendered as inert text",
        created.status == 201 and "&lt;script&gt;" in note_page and "<script>" not in note_page,
        f"note {note_id}: page shows the markup escaped",
    )

    verdicts = [
        bob.api(method, f"/notes/{note_id}", body, csrf="auto").status
        for method, body in (("GET", None), ("PATCH", {"content": "changed"}), ("DELETE", None))
    ]
    check(
        "another user gets 404 for read, update and delete",
        verdicts == [404, 404, 404],
        f"GET, PATCH, DELETE -> {verdicts}",
    )

    no_token = alice.api("POST", "/notes", {"title": "x", "content": "y"}, csrf=None)
    wrong_token = alice.api("DELETE", f"/notes/{note_id}", csrf="not-the-token")
    check(
        "a state-changing request without the CSRF token is refused",
        (no_token.status, wrong_token.status) == (403, 403),
        f"no token -> {no_token.status}, wrong token -> {wrong_token.status}",
    )

    attempts = [
        bob.request(
            "POST",
            "/login",
            form={"username": bob_name, "password": bob_password[::-1], "csrf_token": bob.csrf_token()},
        )
        for _ in range(6)
    ]
    codes = [attempt.status for attempt in attempts]
    check(
        "repeated wrong passwords are throttled",
        codes[:5] == [401] * 5 and codes[5] == 429,
        f"statuses {codes}, Retry-After {attempts[-1].headers.get('Retry-After', 'missing')} s",
    )

    old_cookie = alice.cookie
    alice.request("POST", "/logout", form={"csrf_token": alice.csrf_token()})
    replay = Browser(host, port)
    replay.cookie = old_cookie
    after = replay.request("GET", "/notes", headers={"Accept": "application/json"})
    check(
        "the old session id stops working after sign out",
        after.status == 401,
        f"GET /notes with the old cookie -> {after.status}",
    )
    return steps


def main(argv: list[str] | None = None, *, out: Callable[[str], None] = print) -> int:
    """Run the scenario against ``--host``/``--port`` (default: APP_HOST and APP_PORT) and print one line per step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("APP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8047")))
    args = parser.parse_args(argv)
    steps = run_scenario(args.host, args.port)
    for number, step in enumerate(steps, start=1):
        out(f"{number:>2}. {'PASS' if step.passed else 'FAIL'}  {step.name}\n        {step.detail}")
    failed = [step for step in steps if not step.passed]
    out(f"{len(steps) - len(failed)} of {len(steps)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
