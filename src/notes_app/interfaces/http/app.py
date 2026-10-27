"""The Flask application factory. Routes translate HTTP to use-case calls and back; no rule lives here."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from flask import Flask, Request, Response, g, jsonify, make_response, redirect, render_template, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

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

_log = logging.getLogger("notes_app.http")
_PUBLIC_ENDPOINTS = frozenset({"healthz", "readyz", "static"})
MAX_BODY_BYTES = 64 * 1024


def client_ip(http_request: Request) -> str:
    """The address the request came from (after ProxyFix, when trusted proxies are configured)."""
    return http_request.remote_addr or "unknown"


def wants_json(http_request: Request) -> bool:
    """JSON for API-style requests: a JSON body, an ``Accept`` that prefers JSON, or PATCH and DELETE."""
    if http_request.method in {"PATCH", "DELETE"} or http_request.is_json:
        return True
    return http_request.accept_mimetypes.best_match(["text/html", "application/json"]) == "application/json"


def create_app(container: Container) -> Flask:
    """Build the application around a wired container."""
    settings = container.settings
    weak = settings.weaknesses
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    if weak.raw_note_output:  # UNSAFE_RAW_NOTE_OUTPUT: templates stop encoding what they print
        app.jinja_env.autoescape = False
    if settings.trusted_proxy_count:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count
        )
    cookie = WEAK_COOKIE if weak.weak_session_cookie else HARDENED_COOKIE

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

    if not weak.skip_security_headers:  # UNSAFE_SKIP_SECURITY_HEADERS removes this hook
        app.after_request(apply_security_headers)

    @app.after_request
    def finish(response: Response) -> Response:
        issued: IssuedSession | None = g.get("new_session")
        if issued is not None:
            set_session_cookie(response, issued.raw_token, issued.max_age_seconds, cookie)
        if g.get("clear_cookie"):
            clear_session_cookie(response, cookie)
        if request.endpoint not in _PUBLIC_ENDPOINTS:
            response.headers.setdefault("Cache-Control", "no-store")
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

    @app.context_processor
    def template_context() -> dict[str, Any]:
        session: Session | None = g.get("session")
        user = container.accounts.get_user(session.user_id) if session and session.user_id else None
        return {"csrf_token": session.csrf_token if session else "", "current_user": user}

    _register_pages(app, container)
    _register_notes(app, container)
    _register_errors(app)
    return app


def _user_id() -> int | None:
    session: Session | None = g.get("session")
    return session.user_id if session else None


def _audit_csrf(container: Container, session: Session | None) -> None:
    user_id = session.user_id if session else None
    detail = (("method", request.method), ("path", request.path))
    container.audit.record(AuditEvent(AuditAction.CSRF_REJECTED, "refused", user_id, client_ip(request), detail))


def _ensure_session(container: Container) -> Session:
    """The current session, or a new anonymous one whose cookie is set on this response."""
    session: Session | None = g.session
    if session is None:
        issued = container.sessions.start_anonymous()
        g.new_session = issued
        g.session = issued.session
        session = issued.session
    return session


def _require_user(container: Container) -> int:
    session: Session | None = g.session
    if session is None or session.user_id is None:
        raise _Unauthenticated
    return session.user_id


class _Unauthenticated(Exception):  # noqa: N818 - control flow for the error handler, not a domain error
    """No signed-in session on a route that needs one."""


def _fields() -> dict[str, Any]:
    """The request's input as one mapping: a JSON object or the form fields."""
    if request.is_json:
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}
    return request.form.to_dict()


def _text(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name, "")
    return value if isinstance(value, str) else ""


def _register_pages(app: Flask, container: Container) -> None:
    @app.get("/healthz")
    def healthz() -> ResponseReturnValue:
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz() -> ResponseReturnValue:
        if container.database.ping():
            return jsonify(status="ready")
        return jsonify(status="database unavailable"), 503

    @app.get("/")
    def index() -> ResponseReturnValue:
        return redirect("/notes" if _user_id() else "/login", code=302)

    @app.get("/signup")
    def signup_form() -> ResponseReturnValue:
        _ensure_session(container)
        return render_template("signup.html", error=None)

    @app.post("/signup")
    def signup() -> ResponseReturnValue:
        fields = _fields()
        try:
            container.accounts.register(_text(fields, "username"), _text(fields, "password"), client_ip(request))
        except (InvalidInputError, UsernameTakenError) as error:
            message = error.reason if isinstance(error, InvalidInputError) else "That username is not available."
            return render_template("signup.html", error=message), 400
        return redirect("/login", code=303)

    @app.get("/login")
    def login_form() -> ResponseReturnValue:
        _ensure_session(container)
        return render_template("login.html", error=None)

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

    @app.post("/logout")
    def logout() -> ResponseReturnValue:
        user_id = _user_id()
        container.sessions.sign_out(g.cookie_token)
        g.clear_cookie = True
        if user_id is not None:
            container.audit.record(AuditEvent(AuditAction.LOGOUT, "success", user_id, client_ip(request)))
        return redirect("/login", code=303)


def _register_notes(app: Flask, container: Container) -> None:
    @app.get("/notes")
    def list_notes() -> ResponseReturnValue:
        notes = container.notes.list_visible(_require_user(container))
        if wants_json(request):
            return jsonify(
                notes=[{"id": item.note.id, "title": item.note.title, "role": item.role.value} for item in notes]
            )
        return render_template("notes.html", notes=notes, error=None)

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

    @app.get("/notes/<int:note_id>")
    def show_note(note_id: int) -> ResponseReturnValue:
        note = container.notes.get(_require_user(container), note_id, client_ip(request))
        if wants_json(request):
            return jsonify(id=note.id, title=note.title, content=note.content, owner_id=note.owner_id)
        return render_template("note.html", note=note, error=None)

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

    @app.delete("/notes/<int:note_id>")
    def delete_note(note_id: int) -> ResponseReturnValue:
        container.notes.delete(_require_user(container), note_id, client_ip(request))
        return "", 204

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


def _json_error(status: int, code: str, message: str, **extra: object) -> Response:
    return make_response(jsonify(error=code, message=message, **extra), status)


def _page_error(status: int, title: str, message: str) -> Response:
    return make_response(render_template("error.html", title=title, message=message), status)


def _register_errors(app: Flask) -> None:
    def respond(status: int, code: str, message: str, **extra: object) -> Response:
        if wants_json(request):
            return _json_error(status, code, message, **extra)
        return _page_error(status, message, "")

    handlers: dict[type[Exception], Callable[[Any], Response]] = {
        InvalidInputError: lambda error: respond(400, "invalid_input", error.reason, field=error.field),
        NoteNotFoundError: lambda _: respond(404, "not_found", "Not found"),
        NoteForbiddenError: lambda _: respond(403, "forbidden", "Forbidden"),
        CsrfRejectedError: lambda _: respond(403, "csrf_rejected", "Request refused: missing or wrong CSRF token"),
    }
    for error_type, handler in handlers.items():
        app.register_error_handler(error_type, handler)

    @app.errorhandler(LoginThrottledError)
    def throttled(error: LoginThrottledError) -> Response:
        response = respond(429, "too_many_attempts", "Too many failed sign-ins. Try again later.")
        response.headers["Retry-After"] = str(error.retry_after_seconds)
        return response

    @app.errorhandler(_Unauthenticated)
    def unauthenticated(_: _Unauthenticated) -> ResponseReturnValue:
        if wants_json(request):
            return _json_error(401, "unauthenticated", "Sign in first")
        return redirect("/login", code=303)

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Response:
        status = error.code or 500
        return respond(status, error.name.lower().replace(" ", "_"), error.name)

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> Response:
        _log.exception("unhandled error", extra={"request_id": g.get("request_id"), "path": request.path})
        return respond(500, "internal_error", "Something went wrong")
