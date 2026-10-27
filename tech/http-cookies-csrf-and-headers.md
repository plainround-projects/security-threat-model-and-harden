# HTTP, cookies, CSRF and security headers

## What it is

**HTTP** is how a browser talks to a web server. It is text, one request and one response at a time, and the server does not remember anything between requests by itself. Three browser features are bolted on to make logins and safety work:

- A **cookie** is a small value the server asks the browser to store (`Set-Cookie`) and send back on every later request to the same site (`Cookie`). It is how a server recognizes "the same browser" again.
- **CSRF** (cross-site request forgery) is an attack in which a *different* website makes your browser send a request to the site you are signed in to. The browser attaches your cookie automatically, so the server thinks you did it.
- **Security headers** are response headers that tell the browser to switch on protections.

None of these is a library. They are protocols and conventions, and this repository implements them in `src/notes_app/interfaces/http/security.py` and the hooks in `app.py`.

## Why this repository uses it

Three of the lesson's threats live here: session theft (T1), CSRF (T4) and clickjacking/sniffing/referrer leakage (T6), plus session fixation (T2). Each has a control in code and a test that fails when the control is removed.

## Where it appears

| Path | What it does |
| --- | --- |
| `interfaces/http/security.py` | Cookie name and attributes, the header table, the CSP string, `set_session_cookie`, `clear_session_cookie`. |
| `interfaces/http/app.py` | `load_session`, `enforce_csrf`, `finish` hooks; `Cache-Control: no-store`. |
| `application/sessions.py` | The server-side session: opaque token, hashing, rotation at sign-in, expiry, `csrf_valid`. |
| `interfaces/http/templates/*.html` | The hidden `csrf_token` field in every form. |
| `tests/security/test_session.py`, `tests/unit/test_security_headers.py` | The proofs. |

## How it works underneath

**A sign-in, step by step.**
1. The browser asks for `/login`. The server creates an *anonymous* session (random token, stored hashed, with its own CSRF token) and replies with `Set-Cookie: __Host-session=<token>; ...` and a form containing the CSRF token as a hidden field.
2. The browser posts the form with the cookie. The server checks the CSRF token against the one stored for that session.
3. If the password is right, the server **deletes the old session and creates a new one** with a new token (rotation) and sends a new cookie. An attacker who planted a known session id before sign-in (**session fixation**) now holds a dead id.
4. Every later request carries the cookie; the server hashes it, looks it up, checks the idle and absolute expiry, and loads the user.

**Why the CSRF token works.** A hostile page can make your browser *send* a request with your cookie, but cannot *read* your pages (the browser's same-origin rule), so it cannot learn the token. A request without the right token is refused.

### Ideas you need first

- **HTTP and a header.** HTTP is the text protocol of the web. A message is a first line, then header lines (`Name: value`), a blank line, and an optional body. Headers carry metadata: which cookie, what content type, what the browser should and should not do.
- **A cookie.** A small value the server asks the browser to store (header `Set-Cookie: name=value; attributes`) and the browser sends back automatically with every later request to that site (header `Cookie: name=value`). Without cookies the server cannot tell that two requests come from the same person.
- **A cookie attribute.** A setting stored with the cookie: `HttpOnly` (page scripts cannot read it), `Secure` (only sent over HTTPS), `SameSite=Lax` (not sent on cross-site POSTs), `Path=/` (sent for every path), `Max-Age` (seconds to keep it).
- **An origin.** Scheme, host and port together (`https://example.com:443`). Browsers keep pages from different origins apart: a page from another site can make your browser *send* a request to this site but cannot *read* the answer. That asymmetry is why a secret token in a page defeats CSRF.
- **A token.** A random value used as a password-like proof: here a session id and a CSRF token, both 256 bits from the operating system's secure random source.
- **HTTPS.** HTTP wrapped in TLS encryption. This app expects HTTPS to be ended by a proxy in front of it (`TRUSTED_PROXY_COUNT`).

## Walkthrough of this repository's use

### The cookie

```python
SESSION_COOKIE = "__Host-session"
...
HARDENED_COOKIE = CookieAttributes(http_only=True, secure=True, same_site="Lax")
...
response.set_cookie(SESSION_COOKIE, raw_token, max_age=max_age, httponly=..., secure=..., samesite=..., path="/")
```
- `HttpOnly`: page scripts cannot read the cookie, so an XSS bug cannot steal it.
- `Secure`: the browser sends it only over HTTPS (browsers treat `http://localhost` as secure for this purpose).
- `SameSite=Lax`: the browser does not attach it to cross-site POSTs or sub-requests, which already blocks most CSRF; it is still sent when a user clicks a normal link to the site.
- `Path=/` and no `Domain`: the cookie belongs to exactly this host.
- The `__Host-` name prefix makes the browser *enforce* `Secure`, `Path=/` and no `Domain`; a cookie that breaks those rules is rejected.
- `max_age` is the lifetime in seconds (8 hours for a signed-in session, 15 minutes for the anonymous one; both are settings).
- The value is `secrets.token_urlsafe(32)`: 256 bits, opaque (it carries no data), and only its SHA-256 is stored server-side (`hash_token`). The test asserts it is not shaped like a JWT.

### CSRF

```python
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)
if session is None or not container.sessions.csrf_valid(session, supplied):
```
"Unsafe" methods change state; GET must not. The token is accepted in the `X-CSRF-Token` header (for API calls) or the `csrf_token` form field. `csrf_valid` uses `hmac.compare_digest`. A rejected request is audited with method and path (never the token). The tests also check that another session's token does not work.

### Security headers

```python
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}
```
- **Content-Security-Policy** (CSP): a list of what the page may load. `default-src 'none'` forbids everything by default (so no script can run at all); `style-src 'self'` allows only the app's own stylesheet; `img-src 'self'`; `form-action 'self'` lets forms post only back to this site; `frame-ancestors 'none'` forbids framing (clickjacking); `base-uri 'none'` stops a `<base>` tag from redirecting relative links. Even if encoding failed, a stored `<script>` would find nothing allowed to run.
- **X-Content-Type-Options: nosniff**: the browser must trust the declared content type and not guess.
- **X-Frame-Options: DENY**: the older way to say "never in a frame".
- **Referrer-Policy: no-referrer**: no `Referer` header on outgoing links, so note URLs do not leak.
- **Cross-Origin-Opener-Policy / Resource-Policy: same-origin**: isolate the page and its resources from other sites' windows and embeds.
- **Permissions-Policy**: switches off camera, microphone and location for the page.
- **Strict-Transport-Security** (HSTS): once the browser has seen this over HTTPS, it refuses plain HTTP to this host for two years (63,072,000 seconds).

`apply_security_headers` uses `response.headers.setdefault(...)`, so a handler's own value wins and every response (pages, JSON, errors, static files) gets the rest. `Cache-Control: no-store` is added to every non-public response so the browser and any proxy do not keep copies of private pages.

### Sessions in the application layer

`SessionService` (`application/sessions.py`) implements: `start_anonymous`, `sign_in` (deletes the previous session, purges expired ones, issues a new one), `resolve` (unknown, expired, or idle for 30 minutes means `None`; touches `last_seen_at` at most once a minute), `sign_out` (deletes the server-side row, so a copied cookie is dead). Sign-out is a real server-side delete, not just a cookie clear.

## Try it yourself

1. Run the header tests (no database):
   ```bash
   .venv/bin/pytest tests/unit/test_security_headers.py -v
   ```
   Expect every test to pass.
2. See headers on a live server (`make up`, then `make run` in another terminal):
   ```bash
   curl -sI http://127.0.0.1:8047/login
   ```
   Expect `Content-Security-Policy`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Cache-Control: no-store` and a `Set-Cookie: __Host-session=...` line with `HttpOnly; Secure; Path=/; SameSite=Lax`.
3. Make a CSRF failure on purpose:
   ```bash
   curl -si -X POST -d "username=a&password=b" http://127.0.0.1:8047/login | head -3
   ```
   Expect a `403` status line: no session and no token.
4. Prove the controls (needs `make up`): `make prove` and look for `UNSAFE_SKIP_CSRF`, `UNSAFE_WEAK_SESSION_COOKIE` and `UNSAFE_SKIP_SECURITY_HEADERS` each followed by `FAILS without the control (proven)`.

## Mistakes people make

- Storing the raw session token in the database. A read of the table then yields working cookies.
- Keeping the same session id across sign-in (fixation).
- A CSRF token stored in a cookie the browser sends automatically; here it is in the session on the server and the page.
- Using GET for actions that change data.
- Setting `Secure` but testing over plain `http://` and wondering why nothing signs in.
- A CSP with `unsafe-inline` or `*`, which defeats it.
- Putting claims in the cookie (JWT) when a plain random id plus a server lookup does the job and can be revoked instantly.

## Check yourself

1. What does `HttpOnly` protect against?
   *Page scripts reading the cookie, for example after an XSS bug.*
2. Why can a hostile site not forge a request with the right CSRF token?
   *It can send the request but cannot read your pages, so it never sees the token.*
3. What does the `__Host-` prefix force?
   *`Secure`, `Path=/` and no `Domain`; otherwise the browser rejects the cookie.*
4. Why is the session id replaced at sign-in?
   *So an id an attacker planted beforehand becomes useless.*
5. What does `default-src 'none'` do in the CSP?
   *Forbids loading or running anything not allowed by a more specific rule, including all scripts.*

## Further reading

- MDN, HTTP cookies: https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies
- MDN, CSP: https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP
- OWASP Session Management Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- OWASP CSRF Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- RFC 6265bis (cookies) and RFC 9110 (HTTP semantics): https://www.rfc-editor.org/rfc/rfc9110
