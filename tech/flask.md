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
