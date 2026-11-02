# Flask 3.1

## What it is

Flask is a **web framework** for Python: a library that turns "an HTTP request arrived" into "call this Python function and send back what it returns". **HTTP** is the text protocol browsers use to talk to servers: a **request** (method such as GET or POST, a path such as `/notes/3`, headers, an optional body) goes in, and a **response** (a status code such as 200 or 404, headers, a body) comes out.

Flask is called a **micro**-framework because it gives you routing, request and response objects, templates, and hooks, and leaves everything else (database, users, validation) to you. The pinned version is `flask==3.1.3`.

## Why this repository uses it

The lesson is about the weaknesses of a web app, so the repository needs a small, readable one. In this code Flask is only the **interface layer**: it reads the HTTP request, calls a use case, and turns the result (or the named error) into a response. No security *rule* lives in Flask code. The rules live in `domain/` and `application/`, which cannot import Flask (enforced by `tech/import-linter.md`).

## Where it appears

| Path | What it does with Flask |
| --- | --- |
| `src/notes_app/interfaces/http/app.py` | `create_app(container)`: the application factory, all routes, hooks, error handlers. |
| `src/notes_app/interfaces/http/security.py` | Uses Flask's `Response` to set headers and the session cookie. |
| `src/notes_app/interfaces/wsgi.py` | `build_app()` builds settings, the container and the Flask app for gunicorn. |
| `src/notes_app/interfaces/http/templates/`, `static/` | The HTML pages and the stylesheet Flask serves. |
| `tests/` | `app.test_client()` drives the app without a network (see `tech/pytest.md`). |

## How it works underneath

1. A server (gunicorn) accepts a network connection and parses the HTTP text. It then calls the Flask app as a **WSGI** application: a plain Python callable `app(environ, start_response)` where `environ` is a dictionary describing the request. WSGI is the agreed interface between Python web servers and frameworks.
2. Flask builds a `Request` object from `environ` and finds the function whose route matches the method and path.
3. **Before-request hooks** run in the order they were registered. If one returns a response or raises, the route function is skipped.
4. The route function runs and returns a body, or a body plus status. Flask wraps it in a `Response`.
5. **After-request hooks** run and may change the response (add headers, cookies).
6. If anything raised, Flask looks for a registered **error handler** for that exception class and returns what it returns.
7. `g` is an object that lives for exactly one request: a scratchpad that hooks and routes share. `request` and `g` look like globals but are bound to the current request.

### Ideas you need first

- **A client and a server.** A client (a browser, or a program like `curl`) asks; a server (this app) answers. They talk over the network. A **port** is a number (8047 here) that picks which program on a machine receives the connection, like an apartment number inside a building address. `127.0.0.1` is the machine's own address ("localhost"): connections to it never leave the machine.
- **A request.** One message from client to server. It has a **method** (GET reads something, POST sends something new, PATCH changes part of something, DELETE removes it), a **path** (`/notes/3`), optional **query** text after a `?` (`?scope=x`), **headers** (named pieces of metadata, like `Cookie:` or `Accept:`), and an optional **body** (the data being sent: a form, or JSON).
- **A response.** The reply: a **status code** (200 means OK, 201 created, 204 no content, 302 or 303 "go to another address", 400 bad request, 401 not signed in, 403 forbidden, 404 not found, 413 body too large, 429 too many requests, 500 server error, 503 unavailable), headers, and a body (an HTML page or JSON).
- **JSON.** A text format for data. `{"id": 3, "title": "Groceries"}` is an object with two named values: curly braces hold named values, square brackets hold lists, strings are in double quotes, numbers are bare, and `true`, `false` and `null` are the other values. Python reads it into a dictionary.
- **A form.** An HTML page element that sends the typed values to the server, as a POST with the values URL-encoded in the body (`username=alice&password=...`).
- **A route.** A rule that says "requests for this method and path go to this function". Flask writes it as a decorator: `@app.get("/notes")`. `<int:note_id>` inside a path captures that part and converts it to a whole number.
- **A hook.** A function Flask calls automatically at a fixed moment: `before_request` runs before every route, `after_request` after it.
- **An error handler.** A function Flask calls when an exception of a given class escapes a route. It decides the response.
- **A template.** An HTML file with holes the server fills in (`tech/jinja2-templates.md`).

## Walkthrough of this repository's use

### The application factory

```python
def create_app(container: Container) -> Flask:
    settings = container.settings
    weak = settings.weaknesses
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
```
A **factory** is a function that builds the app, instead of a global `app = Flask(...)` at import time. Tests call it with a container wired to a test database; production calls it through `build_app()`. `MAX_CONTENT_LENGTH` makes Flask refuse any request body over 64 KiB (`MAX_BODY_BYTES = 64 * 1024`) with status 413, so a client cannot make the server read a huge upload.

### The first hook: load the session

```python
@app.before_request
def load_session() -> None:
    g.started = time.perf_counter()
    g.request_id = uuid.uuid4().hex
    g.new_session = None
    g.cookie_token = request.cookies.get(SESSION_COOKIE)
    g.session = None
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return
    g.session = container.sessions.resolve(g.cookie_token)
```
Stores a start time (for the duration log), a random request id (to match log lines), the raw cookie value, and the resolved session on `g`. `_PUBLIC_ENDPOINTS = {"healthz", "readyz", "static"}` are skipped so health probes never touch the database for a session.

### The CSRF hook (a control that can be removed for the proof)

```python
if not weak.skip_csrf:  # UNSAFE_SKIP_CSRF removes this hook

    @app.before_request
    def enforce_csrf() -> None:
        if request.method not in UNSAFE_METHODS or request.endpoint in _PUBLIC_ENDPOINTS:
            return
        session: Session | None = g.session
        supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)
        if session is None or not container.sessions.csrf_valid(session, supplied):
            _audit_csrf(container, session)
            raise CsrfRejectedError("missing or wrong CSRF token")
```
For POST, PUT, PATCH and DELETE, the request must carry the session's CSRF token, either in the `X-CSRF-Token` header (API clients) or the `csrf_token` form field (HTML forms). Otherwise it writes an audit row and raises `CsrfRejectedError`, which an error handler turns into a 403. See `tech/http-cookies-csrf-and-headers.md`.

### After-request hooks

`app.after_request(apply_security_headers)` adds the security headers to every response. The `finish` hook sets or clears the session cookie, adds `Cache-Control: no-store` to non-public responses (so a browser or proxy never caches a page of notes), and writes one JSON log line per request with `request_id`, method, path, status, duration and user id. It never logs the cookie, the form body or the CSRF token.

### Routes

```python
@app.get("/notes/<int:note_id>")
def show_note(note_id: int) -> ResponseReturnValue:
    note = container.notes.get(_require_user(container), note_id, client_ip(request))
    if wants_json(request):
        return jsonify(id=note.id, title=note.title, content=note.content, owner_id=note.owner_id)
    return render_template("note.html", note=note, error=None)
```
`@app.get(path)` is shorthand for a route that accepts only GET (`@app.post`, `@app.patch`, `@app.delete` likewise). `<int:note_id>` captures that part of the path and converts it to an integer; `/notes/abc` never reaches the function and returns 404. `jsonify` builds a JSON response. `render_template` fills an HTML template (see `tech/jinja2-templates.md`). The function contains no authorization logic: `NoteService.get` asks the policy, and raises `NoteNotFoundError` for a note you may not see.

The other routes: `GET /healthz` (always `{"status":"ok"}`), `GET /readyz` (200 only when `container.database.ping()` works, otherwise 503), `GET /` (redirect), `GET/POST /signup`, `GET/POST /login`, `POST /logout`, `GET/POST /notes`, `PATCH/DELETE /notes/<id>`, `POST /notes/<id>/shares`.

`redirect("/notes", code=303)` after a successful POST uses status **303 See Other**: the browser then fetches the target with GET, so a page refresh does not resubmit the form.

### One handler for a few JSON-or-HTML decisions

`wants_json(request)` returns true for PATCH, DELETE, a JSON body, or an `Accept` header that prefers `application/json`, so the same routes serve both the browser pages and the API-style calls the tests and demo use.

### Error handlers

```python
handlers: dict[type[Exception], Callable[[Any], Response]] = {
    InvalidInputError: lambda error: respond(400, "invalid_input", error.reason, field=error.field),
    NoteNotFoundError: lambda _: respond(404, "not_found", "Not found"),
    NoteForbiddenError: lambda _: respond(403, "forbidden", "Forbidden"),
    CsrfRejectedError: lambda _: respond(403, "csrf_rejected", "Request refused: missing or wrong CSRF token"),
}
for error_type, handler in handlers.items():
    app.register_error_handler(error_type, handler)
```
A table from domain error to HTTP outcome. `LoginThrottledError` becomes 429 with a `Retry-After` header. A catch-all `@app.errorhandler(Exception)` logs the traceback (with the request id) and returns a generic 500 body, so a stack trace never reaches the client.

### Behind a proxy

```python
if settings.trusted_proxy_count:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count)
```
See `tech/werkzeug.md`: only when the operator says how many proxies to trust does the app believe `X-Forwarded-For`.

### Weakness switches

`app.jinja_env.autoescape = False` when `UNSAFE_RAW_NOTE_OUTPUT` is on, `WEAK_COOKIE` instead of `HARDENED_COOKIE`, and skipping the two hooks above. These exist so `make prove` can show the tests fail without the control. They are accepted only when `APP_ENV=test`.

### Every route and hook, in order

`create_app(container)` in `interfaces/http/app.py` builds the application. These are all its parts, in the order they appear in the file.

**Setup.** `weak = settings.weaknesses`; `app = Flask(__name__)` (`__name__` is the module's own name, which tells Flask where to find its `templates/` and `static/` folders); `MAX_CONTENT_LENGTH` is set to 65,536; if the weakness `raw_note_output` is on, template escaping is turned off; if `TRUSTED_PROXY_COUNT` is above 0, `ProxyFix` wraps the app (`tech/werkzeug.md`); `cookie` is chosen: the hardened or the deliberately weak cookie attributes.

**Hook `load_session` (before every request).** Stores a start time (`time.perf_counter()` is a precise stopwatch), a random request id (`uuid.uuid4().hex`, 32 hex characters), and the raw cookie value. For the three public endpoints (`healthz`, `readyz`, `static`) it stops there. Otherwise it asks `SessionService.resolve` for the live session and stores it on `g`.

**Hook `enforce_csrf` (before every request; absent when the weakness `skip_csrf` is on).** Lets GET through. For POST, PUT, PATCH and DELETE it reads the token from the `X-CSRF-Token` header or the `csrf_token` form field, and if there is no session or the token does not match, it audits the refusal (method and path only) and raises `CsrfRejectedError`, which becomes a 403.

**Hook `apply_security_headers` (after every request; absent when `skip_security_headers` is on).** Adds the headers (`tech/http-cookies-csrf-and-headers.md`).

**Hook `finish` (after every request).** If a new session was issued, sets the session cookie; if the route asked, clears it; adds `Cache-Control: no-store` to non-public responses; writes one JSON log line with request id, method, path, status, duration in milliseconds and user id. It never logs the cookie, a form value or a header value.

**`template_context`.** Adds `csrf_token` and `current_user` to every template.

**Helpers.** `client_ip(request)` returns the caller's address; `wants_json(request)` is true for PATCH and DELETE, for a JSON body, or when the `Accept` header prefers JSON; `_ensure_session` returns the current session or starts an anonymous one; `_require_user` returns the signed-in user's id or raises the private `_Unauthenticated`; `_fields()` returns the request's input as one dictionary (the JSON object, or the form); `_text(fields, name)` returns a value only if it really is text.

**The 14 routes.**

| Route | Behavior |
| --- | --- |
| `GET /healthz` | Always `{"status":"ok"}`. Liveness: the process is running. |
| `GET /readyz` | `{"status":"ready"}` if `container.database.ping()` works, otherwise 503 `{"status":"database unavailable"}`. This is what the container health check and `make health` call. |
| `GET /` | Redirects (302) to `/notes` if signed in, else to `/login`. |
| `GET /signup` | Starts an anonymous session (so the form has a CSRF token) and renders `signup.html`. |
| `POST /signup` | Registers the user. On invalid input or a taken name it re-renders the form with status 400 and a message (the "taken" message is deliberately vague: "That username is not available."). On success, redirect 303 to `/login`. |
| `GET /login` | Starts an anonymous session and renders `login.html`. |
| `POST /login` | Calls `AccountService.authenticate`. A wrong credential re-renders the form with 401 and "Invalid username or password." (the throttle's 429 comes from the error handler). On success it calls `sign_in` with the old cookie (which deletes the old session: the new session id defeats fixation), stores the new session to be set as a cookie, and redirects 303 to `/notes`. |
| `POST /logout` | Deletes the server-side session, marks the cookie to be cleared, audits `LOGOUT`, redirects 303 to `/login`. |
| `GET /notes` | Lists the notes the user owns or has been given; JSON (`notes=[{id, title, role}]`) or the page. |
| `POST /notes` | Creates a note from the form or JSON. Invalid input: JSON clients get the error handler's 400; form clients get the page again with status 400. Success: JSON 201 `{id}`, or redirect 303 to the note. |
| `GET /notes/<int:note_id>` | Reads one note through the authorization check; JSON or `note.html`. |
| `PATCH /notes/<int:note_id>` | Updates title and/or content (only fields that are text are used); JSON answer. |
| `DELETE /notes/<int:note_id>` | Deletes; answers 204 with an empty body. |
| `POST /notes/<int:note_id>/shares` | Shares with a username; form clients are redirected back to the note (303), JSON clients get 204. |

Why `303` and not `302` after a POST? 303 "See Other" tells the browser to fetch the next address with GET, so refreshing the page does not send the form again.

**Error handlers** (`_register_errors`). `respond(status, code, message)` answers JSON for API-style requests and an HTML page otherwise. The table: `InvalidInputError` is 400 with the field named; `NoteNotFoundError` 404; `NoteForbiddenError` 403; `CsrfRejectedError` 403; `LoginThrottledError` 429 with a `Retry-After` header (seconds to wait); `_Unauthenticated` is 401 JSON or a redirect to `/login`; `HTTPException` (Werkzeug's base for standard errors such as 404 for an unknown path) keeps its own code; and a catch-all `Exception` handler logs the traceback with the request id and answers a generic 500.

### Line by line: `src/notes_app/interfaces/wsgi.py`

```python
"""WSGI entry point: ``gunicorn "notes_app.interfaces.wsgi:build_app()"``."""
```

The docstring shows how gunicorn starts the app. **WSGI** is the Python standard interface between a web server and an application.

```python
from __future__ import annotations

import logging
import os

from flask import Flask

from notes_app.infrastructure.logging import configure_logging
from notes_app.infrastructure.settings import Settings
from notes_app.interfaces.composition import Container, build_container
from notes_app.interfaces.http.app import create_app
```

Imports: `logging`, `os`, `Flask`, the log setup, `Settings`, the container builder and `create_app`.

```python
_containers: list[Container] = []
```

`_containers` remembers every container this process built so shutdown can close them.

```python
def build_app() -> Flask:
    """Read settings from the environment, open the database pool and return the application.

    Raises ``ConfigError`` (and so refuses to start) on a missing or invalid setting.
    """
    settings = Settings.from_environment(os.environ)
    configure_logging(settings.log_level)
    container = build_container(settings)
    container.database.open()
    _containers.append(container)
    logging.getLogger("notes_app").info(
        "started", extra={"app_env": settings.app_env, "weaknesses_enabled": list(settings.weaknesses.enabled())}
    )
```

`build_app` reads and validates the settings from the process environment (a bad or missing setting raises `ConfigError` and the process stops), sets up JSON logging, builds the container, opens the database pool (a database that is down also stops start-up), remembers the container and logs `started` with the environment name and the list of enabled weaknesses.

```python
    if settings.weaknesses.enabled():
        logging.getLogger("notes_app").warning("deliberate weaknesses are ON; this is a test run")
    return create_app(container)
```

If any weakness is on, a warning says this is a test run. The Flask application is returned.

```python
def close_all() -> None:
    """Close the database pools of every application this process built (graceful shutdown)."""
    while _containers:
        _containers.pop().database.close()
    logging.getLogger("notes_app").info("database pool closed")
```

`close_all` closes the pool of every container; `pop()` removes the last list item each time round the `while` loop.

### Line by line: `src/notes_app/interfaces/http/app.py`

This is the web layer. Flask turns each HTTP request into a call of a Python function (a **route**) and each return value into a response. The routes only translate between HTTP and the use cases; no business rule lives here.

```python
"""The Flask application factory. Routes translate HTTP to use-case calls and back; no rule lives here."""

from __future__ import annotations
```

The docstring and the type-hint line.

```python
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any
```

Imports: `logging`; `time` (a precise clock for request timing); `uuid` (random unique ids); `Callable` and `Any` for type hints.

```python
from flask import Flask, Request, Response, g, jsonify, make_response, redirect, render_template, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
```

From Flask: the application class; `Request` and `Response` types; `g` (an object that lives for one request and carries data between hooks and routes); `jsonify` (builds a JSON response); `make_response`, `redirect`, `render_template` (fills an HTML template) and `request` (the current request). `ResponseReturnValue` is the type of what a route may return. `HTTPException` is the base of Werkzeug's HTTP errors (404, 413 and so on). `ProxyFix` is a wrapper that reads the `X-Forwarded-For` headers of a trusted reverse proxy.

```python
from notes_app.application.sessions import IssuedSession
from notes_app.domain.errors import (
    AuthenticationFailedError,
    CsrfRejectedError,
    InvalidInputError,
    LoginThrottledError,
    NoteForbiddenError,
    NoteNotFoundError,
    UsernameTakenError,
)
from notes_app.domain.models import AuditAction, AuditEvent, Session
from notes_app.interfaces.composition import Container
from notes_app.interfaces.http.security import (
    CSRF_FIELD,
    CSRF_HEADER,
    HARDENED_COOKIE,
    SESSION_COOKIE,
    UNSAFE_METHODS,
    WEAK_COOKIE,
    apply_security_headers,
    clear_session_cookie,
    set_session_cookie,
)
```

Imports of the session type, the domain errors, the models, the container and the security helpers.

```python
_log = logging.getLogger("notes_app.http")
_PUBLIC_ENDPOINTS = frozenset({"healthz", "readyz", "static"})
MAX_BODY_BYTES = 64 * 1024
```

`_log` is the logger `notes_app.http`. `_PUBLIC_ENDPOINTS` are the routes that need no session (health checks and static files). `MAX_BODY_BYTES` is 64 KiB (65,536 bytes).

```python
def client_ip(http_request: Request) -> str:
    """The address the request came from (after ProxyFix, when trusted proxies are configured)."""
    return http_request.remote_addr or "unknown"
```

`client_ip` returns the address of the client as Flask sees it, or `unknown`. After `ProxyFix` it is the real client rather than the proxy.

```python
def wants_json(http_request: Request) -> bool:
    """JSON for API-style requests: a JSON body, an ``Accept`` that prefers JSON, or PATCH and DELETE."""
    if http_request.method in {"PATCH", "DELETE"} or http_request.is_json:
        return True
    return http_request.accept_mimetypes.best_match(["text/html", "application/json"]) == "application/json"
```

`wants_json` decides whether to answer with JSON: yes for PATCH and DELETE, for a request whose body is JSON, or when the `Accept` header prefers JSON over HTML.

```python
def create_app(container: Container) -> Flask:
    """Build the application around a wired container."""
    settings = container.settings
    weak = settings.weaknesses
    app = Flask(__name__)
```

`create_app` builds the application around a container; `Flask(__name__)` creates it.

```python
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    if weak.raw_note_output:  # UNSAFE_RAW_NOTE_OUTPUT: templates stop encoding what they print
        app.jinja_env.autoescape = False
```

The body size limit is set; larger bodies get HTTP 413. If the weakness `raw_note_output` is on, the template engine's automatic output encoding is switched off: notes are then printed raw, which makes stored cross-site scripting possible and lets a test prove that encoding is the control.

```python
    if settings.trusted_proxy_count:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count
        )
```

If trusted proxies are configured, the WSGI app is wrapped in `ProxyFix`, which believes the forwarded address and scheme from exactly that many proxies. With zero, the headers are ignored, because anyone can send a fake `X-Forwarded-For`.

```python
    cookie = WEAK_COOKIE if weak.weak_session_cookie else HARDENED_COOKIE
```

Choose the cookie attributes: the weak ones only for the weakness, otherwise the hardened ones.

```python
    @app.before_request
    def load_session() -> None:
        g.started = time.perf_counter()
        g.request_id = uuid.uuid4().hex
        g.new_session = None
        g.cookie_token = request.cookies.get(SESSION_COOKIE)
        g.session = None
```

`@app.before_request` registers a function that runs before every request. It records the start time and a request id, clears the new-session slot, reads the session cookie into `g.cookie_token`, and starts with no session.

```python
        if request.endpoint in _PUBLIC_ENDPOINTS:
            return
        g.session = container.sessions.resolve(g.cookie_token)
```

Public endpoints stop here. For every other request the cookie is resolved into a live session or `None`.

```python
    if not weak.skip_csrf:  # UNSAFE_SKIP_CSRF removes this hook

        @app.before_request
        def enforce_csrf() -> None:
            if request.method not in UNSAFE_METHODS or request.endpoint in _PUBLIC_ENDPOINTS:
                return
            session: Session | None = g.session
            supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)
            if session is None or not container.sessions.csrf_valid(session, supplied):
                _audit_csrf(container, session)
                raise CsrfRejectedError("missing or wrong CSRF token")
```

The CSRF hook is registered only when the `skip_csrf` weakness is off. For an unsafe method (POST, PUT, PATCH, DELETE) on a non-public route it takes the token from the `X-CSRF-Token` header or the form field. If there is no session or the token is not valid for it, the attempt is audited and `CsrfRejectedError` is raised (answered 403).

```python
    if not weak.skip_security_headers:  # UNSAFE_SKIP_SECURITY_HEADERS removes this hook
        app.after_request(apply_security_headers)
```

The security headers are added to every response unless the weakness is on.

```python
    @app.after_request
    def finish(response: Response) -> Response:
        issued: IssuedSession | None = g.get("new_session")
        if issued is not None:
            set_session_cookie(response, issued.raw_token, issued.max_age_seconds, cookie)
        if g.get("clear_cookie"):
            clear_session_cookie(response, cookie)
```

`@app.after_request` runs after every request. If a route stored a new session, its cookie is set; if a route asked for it (`clear_cookie`), the cookie is cleared.

```python
        if request.endpoint not in _PUBLIC_ENDPOINTS:
            response.headers.setdefault("Cache-Control", "no-store")
```

Every non-public response gets `Cache-Control: no-store` unless already set, so pages with private data are not kept by caches.

```python
        _log.info(
            "request",
            extra={
                "request_id": g.get("request_id"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - g.get("started", time.perf_counter())) * 1000, 1),
                "user_id": _user_id(),
            },
        )
        return response
```

One log line `request` is written with the request id, method, path, status, the duration in milliseconds and the user id. The response is returned.

```python
    @app.context_processor
    def template_context() -> dict[str, Any]:
        session: Session | None = g.get("session")
        user = container.accounts.get_user(session.user_id) if session and session.user_id else None
        return {"csrf_token": session.csrf_token if session else "", "current_user": user}
```

`@app.context_processor` adds values to every template: the CSRF token of the current session (empty if none) and the signed-in user (looked up for the page header).

```python
    _register_pages(app, container)
    _register_notes(app, container)
    _register_errors(app)
    return app
```

The page routes, the note routes and the error handlers are registered, and the application is returned.

```python
def _user_id() -> int | None:
    session: Session | None = g.get("session")
    return session.user_id if session else None
```

`_user_id` returns the signed-in user's id or `None`.

```python
def _audit_csrf(container: Container, session: Session | None) -> None:
    user_id = session.user_id if session else None
    detail = (("method", request.method), ("path", request.path))
    container.audit.record(AuditEvent(AuditAction.CSRF_REJECTED, "refused", user_id, client_ip(request), detail))
```

`_audit_csrf` writes a `csrf.rejected` audit row with the method and the path.

```python
def _ensure_session(container: Container) -> Session:
    """The current session, or a new anonymous one whose cookie is set on this response."""
    session: Session | None = g.session
    if session is None:
        issued = container.sessions.start_anonymous()
        g.new_session = issued
        g.session = issued.session
        session = issued.session
    return session
```

`_ensure_session` returns the current session, or starts an anonymous one and marks it so the response sets its cookie. The sign-in and sign-up forms need it for their CSRF token.

```python
def _require_user(container: Container) -> int:
    session: Session | None = g.session
    if session is None or session.user_id is None:
        raise _Unauthenticated
    return session.user_id
```

`_require_user` returns the signed-in user's id, or raises `_Unauthenticated`.

```python
class _Unauthenticated(Exception):  # noqa: N818 - control flow for the error handler, not a domain error
    """No signed-in session on a route that needs one."""
```

`_Unauthenticated` is an exception used as control flow for the error handler; the `noqa` comment explains why its name does not end in `Error`.

```python
def _fields() -> dict[str, Any]:
    """The request's input as one mapping: a JSON object or the form fields."""
    if request.is_json:
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}
    return request.form.to_dict()
```

`_fields` reads the request input as one dictionary, from a JSON object or from the form. A body that is not an object gives an empty dictionary.

```python
def _text(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name, "")
    return value if isinstance(value, str) else ""
```

`_text` returns a field if it is text, else the empty text, so a number or list in a JSON body can never reach a validator.

```python
def _register_pages(app: Flask, container: Container) -> None:
    @app.get("/healthz")
    def healthz() -> ResponseReturnValue:
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz() -> ResponseReturnValue:
        if container.database.ping():
            return jsonify(status="ready")
        return jsonify(status="database unavailable"), 503
```

Page routes. `GET /healthz` answers `{"status": "ok"}` to say the process is alive. `GET /readyz` answers ready if the database ping works, else status 503.

```python
    @app.get("/")
    def index() -> ResponseReturnValue:
        return redirect("/notes" if _user_id() else "/login", code=302)
```

`GET /` redirects (302) to the notes list when signed in, else to the login page.

```python
    @app.get("/signup")
    def signup_form() -> ResponseReturnValue:
        _ensure_session(container)
        return render_template("signup.html", error=None)
```

`GET /signup` makes sure there is an anonymous session (for the CSRF token) and shows the form.

```python
    @app.post("/signup")
    def signup() -> ResponseReturnValue:
        fields = _fields()
        try:
            container.accounts.register(_text(fields, "username"), _text(fields, "password"), client_ip(request))
        except (InvalidInputError, UsernameTakenError) as error:
            message = error.reason if isinstance(error, InvalidInputError) else "That username is not available."
            return render_template("signup.html", error=message), 400
        return redirect("/login", code=303)
```

`POST /signup` registers the user. A validation error or a taken name shows the form again with status 400; the taken-name message is deliberately vague (`That username is not available.`). Success redirects with 303 to the login page (303 tells the browser to follow with a GET).

```python
    @app.get("/login")
    def login_form() -> ResponseReturnValue:
        _ensure_session(container)
        return render_template("login.html", error=None)
```

`GET /login` shows the form.

```python
    @app.post("/login")
    def login() -> ResponseReturnValue:
        fields = _fields()
        try:
            user = container.accounts.authenticate(
                _text(fields, "username"), _text(fields, "password"), client_ip(request)
            )
        except AuthenticationFailedError:
            return render_template("login.html", error="Invalid username or password."), 401
        issued = container.sessions.sign_in(g.cookie_token, user.id)
        g.new_session = issued
        return redirect("/notes", code=303)
```

`POST /login` authenticates. A failure shows one fixed message with status 401, so the page never says which part was wrong. Success rotates the session (`sign_in` receives the old cookie and issues a new one) and redirects to `/notes`. A throttled client raises `LoginThrottledError`, answered by the handler below.

```python
    @app.post("/logout")
    def logout() -> ResponseReturnValue:
        user_id = _user_id()
        container.sessions.sign_out(g.cookie_token)
        g.clear_cookie = True
        if user_id is not None:
            container.audit.record(AuditEvent(AuditAction.LOGOUT, "success", user_id, client_ip(request)))
        return redirect("/login", code=303)
```

`POST /logout` deletes the server-side session, asks for the cookie to be cleared, writes a `logout` audit row for a signed-in user and redirects to the login page. A logout is a POST so a link or image on another site cannot trigger it.

```python
def _register_notes(app: Flask, container: Container) -> None:
    @app.get("/notes")
    def list_notes() -> ResponseReturnValue:
        notes = container.notes.list_visible(_require_user(container))
        if wants_json(request):
            return jsonify(
                notes=[{"id": item.note.id, "title": item.note.title, "role": item.role.value} for item in notes]
            )
        return render_template("notes.html", notes=notes, error=None)
```

`GET /notes` lists the visible notes for the signed-in user (a missing session raises `_Unauthenticated`), as JSON or as HTML depending on `wants_json`.

```python
    @app.post("/notes")
    def create_note() -> ResponseReturnValue:
        user_id = _require_user(container)
        fields = _fields()
        try:
            note = container.notes.create(user_id, _text(fields, "title"), _text(fields, "content"))
        except InvalidInputError as error:
            if wants_json(request):
                raise
            return render_template("notes.html", notes=container.notes.list_visible(user_id), error=error.reason), 400
        if wants_json(request):
            return jsonify(id=note.id), 201
        return redirect(f"/notes/{note.id}", code=303)
```

`POST /notes` creates a note. For HTML a validation error re-renders the list with status 400; for JSON the error is raised and the handler answers. Success gives 201 with the id for JSON or redirects to the note page.

```python
    @app.get("/notes/<int:note_id>")
    def show_note(note_id: int) -> ResponseReturnValue:
        note = container.notes.get(_require_user(container), note_id, client_ip(request))
        if wants_json(request):
            return jsonify(id=note.id, title=note.title, content=note.content, owner_id=note.owner_id)
        return render_template("note.html", note=note, error=None)
```

`GET /notes/<int:note_id>` shows a note. `<int:note_id>` matches only whole numbers. The service does the authorization.

```python
    @app.patch("/notes/<int:note_id>")
    def update_note(note_id: int) -> ResponseReturnValue:
        fields = _fields()
        title = fields.get("title")
        content = fields.get("content")
        note = container.notes.update(
            _require_user(container),
            note_id,
            title if isinstance(title, str) else None,
            content if isinstance(content, str) else None,
            client_ip(request),
        )
        return jsonify(id=note.id, title=note.title, content=note.content)
```

`PATCH /notes/<id>` updates a note: each field is used only if it is text, otherwise `None` meaning "unchanged". The answer is the new note.

```python
    @app.delete("/notes/<int:note_id>")
    def delete_note(note_id: int) -> ResponseReturnValue:
        container.notes.delete(_require_user(container), note_id, client_ip(request))
        return "", 204
```

`DELETE /notes/<id>` deletes and answers 204 (no content).

```python
    @app.post("/notes/<int:note_id>/shares")
    def share_note(note_id: int) -> ResponseReturnValue:
        user_id = _require_user(container)
        fields = _fields()
        try:
            container.notes.share(user_id, note_id, _text(fields, "username"), client_ip(request))
        except InvalidInputError as error:
            if wants_json(request):
                raise
            note = container.notes.get(user_id, note_id, client_ip(request))
            return render_template("note.html", note=note, error=error.reason), 400
        if wants_json(request):
            return "", 204
        return redirect(f"/notes/{note_id}", code=303)
```

`POST /notes/<id>/shares` shares a note with a username: an invalid target re-renders the note page with status 400 (or raises for JSON); success answers 204 or redirects.

```python
def _json_error(status: int, code: str, message: str, **extra: object) -> Response:
    return make_response(jsonify(error=code, message=message, **extra), status)
```

`_json_error` builds a JSON error response with a code, a message and optional extra fields.

```python
def _page_error(status: int, title: str, message: str) -> Response:
    return make_response(render_template("error.html", title=title, message=message), status)
```

`_page_error` renders `error.html` with the status.

```python
def _register_errors(app: Flask) -> None:
    def respond(status: int, code: str, message: str, **extra: object) -> Response:
        if wants_json(request):
            return _json_error(status, code, message, **extra)
        return _page_error(status, message, "")
```

`respond` picks JSON or HTML for an error.

```python
    handlers: dict[type[Exception], Callable[[Any], Response]] = {
        InvalidInputError: lambda error: respond(400, "invalid_input", error.reason, field=error.field),
        NoteNotFoundError: lambda _: respond(404, "not_found", "Not found"),
        NoteForbiddenError: lambda _: respond(403, "forbidden", "Forbidden"),
        CsrfRejectedError: lambda _: respond(403, "csrf_rejected", "Request refused: missing or wrong CSRF token"),
    }
    for error_type, handler in handlers.items():
        app.register_error_handler(error_type, handler)
```

A table maps error types to handlers: invalid input gives 400 with the field name; a note not found gives 404; forbidden gives 403; a rejected CSRF gives 403. A loop registers each with Flask.

```python
    @app.errorhandler(LoginThrottledError)
    def throttled(error: LoginThrottledError) -> Response:
        response = respond(429, "too_many_attempts", "Too many failed sign-ins. Try again later.")
        response.headers["Retry-After"] = str(error.retry_after_seconds)
        return response
```

A throttled sign-in gives 429 and a `Retry-After` header with the seconds to wait.

```python
    @app.errorhandler(_Unauthenticated)
    def unauthenticated(_: _Unauthenticated) -> ResponseReturnValue:
        if wants_json(request):
            return _json_error(401, "unauthenticated", "Sign in first")
        return redirect("/login", code=303)
```

An unauthenticated request gets 401 JSON or a redirect to the login page.

```python
    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Response:
        status = error.code or 500
        return respond(status, error.name.lower().replace(" ", "_"), error.name)
```

Any Werkzeug HTTP error (unknown path 404, wrong method 405, too-large body 413) becomes the same shape of answer, with a name made from the status text.

```python
    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> Response:
        _log.exception("unhandled error", extra={"request_id": g.get("request_id"), "path": request.path})
        return respond(500, "internal_error", "Something went wrong")
```

Any other exception is a bug: it is logged with its stack trace and the request id, and the client gets a fixed 500 message with no details.

## Try it yourself

1. List the app's routes without a database (the factory only needs a container object, so use a tiny script):
   ```bash
   .venv/bin/python - <<'EOF'
   import re, pathlib
   src = pathlib.Path("src/notes_app/interfaces/http/app.py").read_text()
   for m in re.finditer(r'@app\.(get|post|patch|delete)\("([^"]+)"\)', src):
       print(m.group(1).upper().ljust(7), m.group(2))
   EOF
   ```
   Expect 14 lines such as `GET     /healthz` and `PATCH   /notes/<int:note_id>`.
2. With the stack running (`make up`, then `make run` in one terminal), probe it from another:
   ```bash
   curl -si http://127.0.0.1:8047/healthz | head -12
   ```
   Expect `HTTP/1.1 200 OK`, a JSON body `{"status":"ok"}`, and the security headers listed in `tech/http-cookies-csrf-and-headers.md`.
3. See the 303 and the cookie flags:
   ```bash
   curl -si http://127.0.0.1:8047/ | head -5
   ```
   Expect `302 FOUND` with `Location: /login`.
4. Run the HTTP-level unit tests, which use the test client and fakes:
   ```bash
   .venv/bin/pytest tests/unit/test_http_app.py -q
   ```
   Expect all to pass, with no database.

## Mistakes people make

- Putting business rules in route functions. Here routes only translate; rules are tested without Flask.
- Running Flask's built-in development server in production. This repository serves with gunicorn (`tech/gunicorn.md`).
- Returning exception text to the client. The catch-all handler returns `Something went wrong` and logs the details instead.
- Trusting `X-Forwarded-For` blindly. `ProxyFix` is added only when `TRUSTED_PROXY_COUNT` is set.
- Forgetting a body-size limit. `MAX_CONTENT_LENGTH` is set.
- Reading a global `app` at import time, which makes tests share state. The factory avoids it.

## Check yourself

1. What is WSGI?
   *The interface between a Python web server and a Python web application: a callable taking `environ` and `start_response`.*
2. What is `g`?
   *A per-request scratchpad shared by hooks and routes.*
3. Why `redirect(..., code=303)` after a POST?
   *The browser follows it with GET, so refreshing does not resend the form.*
4. Where does the rule "only the owner may delete" live?
   *In `domain/access.py` and `application/notes.py`, not in a Flask route.*
5. What makes the catch-all error handler safe?
   *It logs the details with a request id and returns a generic message, so no internals reach the client.*

## Further reading

- Flask 3.1 documentation: https://flask.palletsprojects.com/en/stable/
- Application factories: https://flask.palletsprojects.com/en/stable/patterns/appfactories/
- Handling application errors: https://flask.palletsprojects.com/en/stable/errorhandling/
- WSGI: https://wsgi.readthedocs.io/
