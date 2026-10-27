"""Helpers shared by the HTTP-level tests: a cookie-keeping client that behaves like a browser on https://localhost."""

from __future__ import annotations

import re
import secrets
from typing import Any

from flask import Flask
from werkzeug.test import TestResponse

from notes_app.interfaces.http.security import CSRF_HEADER, SESSION_COOKIE

_CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
HOSTILE = "<script>alert(1)</script> and a quote: ' OR '1'='1"


def new_password() -> str:
    """A fresh generated password, so no credential is ever written in a test."""
    return secrets.token_urlsafe(18)


def new_username(prefix: str = "user") -> str:
    """A unique valid username."""
    return f"{prefix}_{secrets.token_hex(4)}"


class Browser:
    """One person's browser: its own cookie jar, talking to the app over https on localhost."""

    def __init__(self, app: Flask, remote_addr: str = "127.0.0.1") -> None:
        self.client = app.test_client()
        self.remote_addr = remote_addr

    def request(self, method: str, path: str, **kwargs: Any) -> TestResponse:
        kwargs.setdefault("base_url", "https://localhost")
        kwargs.setdefault("environ_base", {"REMOTE_ADDR": self.remote_addr})
        return self.client.open(path, method=method, **kwargs)

    def get(self, path: str, **kwargs: Any) -> TestResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> TestResponse:
        return self.request("POST", path, **kwargs)

    def csrf_token(self) -> str:
        """The CSRF token of the current session, read from a form the way a browser would."""
        match = _CSRF_FIELD.search(self.get("/login").get_data(as_text=True))
        assert match is not None, "the sign-in page carries a CSRF token"
        return match.group(1)

    def api(self, method: str, path: str, *, json: Any = None, csrf: str | None = "auto") -> TestResponse:
        """A JSON request. ``csrf="auto"`` sends the session's token, ``None`` sends none, anything else sends it."""
        headers = {"Accept": "application/json"}
        token = self.csrf_token() if csrf == "auto" else csrf
        if token is not None:
            headers[CSRF_HEADER] = token
        return self.request(method, path, json=json, headers=headers)

    def sign_up(self, username: str, password: str) -> TestResponse:
        data = {"username": username, "password": password, "csrf_token": self.csrf_token()}
        return self.post("/signup", data=data)

    def sign_in(self, username: str, password: str) -> TestResponse:
        data = {"username": username, "password": password, "csrf_token": self.csrf_token()}
        return self.post("/login", data=data)

    def register(self, prefix: str = "user") -> tuple[str, str]:
        """Sign up and sign in a new user; returns the username and the generated password."""
        username, password = new_username(prefix), new_password()
        assert self.sign_up(username, password).status_code == 303
        assert self.sign_in(username, password).status_code == 303
        return username, password

    def session_cookie(self) -> str | None:
        cookie = self.client.get_cookie(SESSION_COOKIE, domain="localhost")
        return None if cookie is None else cookie.value

    def create_note(self, title: str = "A note", content: str = "some text") -> int:
        response = self.api("POST", "/notes", json={"title": title, "content": content})
        assert response.status_code == 201, response.get_data(as_text=True)
        return int(response.get_json()["id"])
