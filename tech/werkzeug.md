# Werkzeug 3.1

## What it is

Werkzeug is the library underneath Flask. It implements the details of HTTP in Python: parsing a request, building a response, cookies, headers, routing URLs to functions, a test client, and middleware. **Middleware** is a wrapper around a WSGI application that can change the request on the way in and the response on the way out. Flask imports Werkzeug automatically, so it is installed as Flask's dependency and pinned in the lock file (`werkzeug==3.1.9`).

## Why this repository uses it

Three small, visible uses: the `HTTPException` base class (so one error handler can catch every standard HTTP error), the `ProxyFix` middleware (to read the real client address behind a reverse proxy), and the **test client** (to send requests to the app without opening a network port).

## Where it appears

| Path | What it does with Werkzeug |
| --- | --- |
| `src/notes_app/interfaces/http/app.py` | `from werkzeug.exceptions import HTTPException` and `from werkzeug.middleware.proxy_fix import ProxyFix`. |
| `tests/support.py` | `from werkzeug.test import TestResponse`; the `Browser` helper wraps `app.test_client()`, which is Werkzeug's client. |
| `src/notes_app/interfaces/http/security.py` | Flask's `Response.set_cookie` and `delete_cookie` are Werkzeug's. |

## How it works underneath

1. A reverse proxy (a server in front of your app, such as nginx or a cloud load balancer) accepts the browser's connection and opens a new one to your app. From the app's point of view every request now comes from the proxy's address.
2. To keep the real address, the proxy adds a header: `X-Forwarded-For: <client address>` (and `X-Forwarded-Proto: https`). Each proxy in a chain appends its own entry.
3. Anyone can also *send* an `X-Forwarded-For` header themselves. So an app must only believe the entries added by proxies it trusts.
4. `ProxyFix(app, x_for=N)` says "trust exactly N proxies" and rewrites `request.remote_addr` from the Nth entry from the right.

## Walkthrough of this repository's use

### `ProxyFix`

```python
if settings.trusted_proxy_count:
    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
        app.wsgi_app, x_for=settings.trusted_proxy_count, x_proto=settings.trusted_proxy_count
    )
```
`settings.trusted_proxy_count` comes from the environment variable `TRUSTED_PROXY_COUNT` (default 0, meaning "no proxy, believe nothing"). `app.wsgi_app` is the inner WSGI callable inside Flask; wrapping it puts `ProxyFix` in front of Flask's own handling. `x_for` is how many `X-Forwarded-For` entries to trust; `x_proto` does the same for `X-Forwarded-Proto` so Flask knows the original scheme was `https`. The comment `# type: ignore[method-assign]` silences `mypy`, which dislikes reassigning a method; this is the documented way to apply the middleware.

Why it matters here: the sign-in throttle's key is `f"{ip}|{username}"` (see `application/accounts.py`) and the audit trail records the address. If the address were always the proxy's, one attacker would lock out everyone, or the audit log would be useless. If the app trusted a forged header, the attacker could pick a new "address" on every guess and escape the throttle. Setting the count correctly avoids both.

### `HTTPException`

```python
@app.errorhandler(HTTPException)
def http_error(error: HTTPException) -> Response:
    status = error.code or 500
    return respond(status, error.name.lower().replace(" ", "_"), error.name)
```
Every standard HTTP error that Werkzeug raises (404 for an unknown path, 405 for a wrong method, 413 for a body over the limit) is an `HTTPException` with a `code` and a `name` such as `Not Found`. One handler turns all of them into the same JSON or HTML shape, using the name and never any internal text.

### The test client

```python
class Browser:
    def __init__(self, app: Flask, remote_addr: str = "127.0.0.1") -> None:
        self.client = app.test_client()
        ...
    def request(self, method: str, path: str, **kwargs: Any) -> TestResponse:
        kwargs.setdefault("base_url", "https://localhost")
        kwargs.setdefault("environ_base", {"REMOTE_ADDR": self.remote_addr})
        return self.client.open(path, method=method, **kwargs)
```
`app.test_client()` builds a fake WSGI environment and calls the app directly, with a **cookie jar** (it remembers `Set-Cookie` headers and sends them back, like a browser). `base_url="https://localhost"` is important: the session cookie is `Secure`, and the client only returns a Secure cookie to an `https` URL. `environ_base={"REMOTE_ADDR": ...}` sets the client address, which the throttle tests change to simulate different clients.

## Try it yourself

1. Watch `ProxyFix` change the visible address:
   ```bash
   .venv/bin/python - <<'EOF'
   from flask import Flask, request
   from werkzeug.middleware.proxy_fix import ProxyFix
   app = Flask(__name__)
   @app.get("/")
   def home(): return request.remote_addr
   plain = app.test_client().get("/", headers={"X-Forwarded-For": "203.0.113.9"})
   app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
   fixed = app.test_client().get("/", headers={"X-Forwarded-For": "203.0.113.9"})
   print(plain.text, fixed.text)
   EOF
   ```
   Expect `127.0.0.1 203.0.113.9`: the header is ignored until `ProxyFix` is applied.
2. See the body limit:
   ```bash
   .venv/bin/python -m pytest tests/unit/test_http_app.py -q -k oversized 2>&1 | tail -3
   ```
   Expect `1 passed`: a body over 64 KiB is refused.
3. Look at an `HTTPException` from the standard library of errors:
   ```bash
   .venv/bin/python -c "from werkzeug.exceptions import NotFound; e = NotFound(); print(e.code, e.name)"
   ```
   Expect `404 Not Found`.

## Mistakes people make

- Trusting `X-Forwarded-For` when there is no proxy, or trusting too many entries. The default here is zero.
- Calling the test client with `http://` and wondering why Secure cookies vanish.
- Reading `request.remote_addr` and assuming it is the user when a proxy is in front. See the section above.

## Check yourself

1. What is middleware?
   *A wrapper around a WSGI app that can change requests before and responses after.*
2. What does `x_for=1` mean?
   *Trust exactly one proxy and take the client address from the last `X-Forwarded-For` entry it added.*
3. Why does the test `Browser` use `https://localhost`?
   *The session cookie is `Secure`; the client only sends it back over https.*
4. What does `HTTPException.code` hold?
   *The numeric HTTP status, such as 404.*
5. Why default `TRUSTED_PROXY_COUNT` to 0?
   *Believing a forwarded header from the open internet lets an attacker forge their address.*

## Further reading

- Werkzeug 3.1 documentation: https://werkzeug.palletsprojects.com/en/stable/
- Middleware, `ProxyFix`: https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/
- Test client: https://werkzeug.palletsprojects.com/en/stable/test/
