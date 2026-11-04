# security-threat-model-and-harden

A small notes app (sign up, sign in, write notes, share one with another user), threat-modeled with STRIDE on one page and hardened control by control, with a test for each control and a way to show that each test fails when its control is removed: "secure" is a suite that runs, not a claim.

| | |
| --- | --- |
| **Lesson** | `/prep/security/project-threat-model-and-harden`, "Threat-model a web app and prove each fix" (`data-structure-explainer/src/content/tracks/security/23-project-threat-model-and-harden.md` in the Plainround app) |
| **Planned hours** | 8 |
| **Level** | Beginner |
| **Architecture** | [ARCHITECTURE.md](ARCHITECTURE.md); threat model and verification note: [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md); decisions: [docs/adr](docs/adr) |
| **Technology notes** | [tech/](tech/README.md): one beginner-level note per technology used here (Python, Bash, Make, Flask, PostgreSQL, Docker and the rest), written through this repository's own files |

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img alt="A browser talks over HTTPS to a Flask app inside one gunicorn process; the application services apply the domain rules and reach PostgreSQL 18 through ports, and a weaknesses folder lets make prove remove each control." src="docs/diagrams/architecture.svg">
</picture>

Every arrow is a trust boundary with a control and a test behind it, and the amber note shows how make prove removes a control to watch its test fail.

## How one run flows

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/flow-dark.svg">
  <img alt="A signed-in user's PATCH /notes/42 passes session lookup, the CSRF check, the access policy, validation and parameter binding before the response leaves with its headers." src="docs/diagrams/flow.svg">
</picture>

The amber rows show the two refusals on the way: a wrong CSRF token is a 403 and a note you cannot see is a 404, each with an audit row.

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Docker with Compose v2 | 24 or newer (tested with 24.0.6) | PostgreSQL 18 |
| Python | 3.12 or 3.13 (tested with 3.13; the CI uses 3.12) | the app and the tests |
| GNU Make | 3.81 or newer | every command below |
| PostgreSQL image | `postgres:18` | pulled on first `make up` |
| Python packages | Flask 3, gunicorn, psycopg 3 with its pool, argon2-cffi at run time; pytest, pytest-cov, httpx, ruff, mypy, import-linter, pip-audit, cyclonedx-bom for development. All pinned with hashes in `requirements.lock` and `requirements-dev.lock`; `make` installs them into `.venv/` | everything |

No cloud account. Every credential is read from the environment: `make up` copies `.env.example` to `.env` the first time (throwaway values for a database that lives on this machine while its container runs). Ports 5471 (PostgreSQL) and 8047 (the app) must be free; both are set in `.env`.

A browser note: the session cookie is `Secure` (the `__Host-` prefix requires it). Chrome and Firefox accept it on `http://localhost`; Safari does not, so use another browser for the local pages or put a TLS proxy in front. The tests and `make demo` do not need a browser.

## Setup, run, test, stop

```bash
make up                  # PostgreSQL 18, then sql/001_schema.sql, 002_seed.sql and sql/migrations/*.sql
make run                 # the app on http://127.0.0.1:8047 (gunicorn, foreground; Ctrl-C shuts it down gracefully)
make demo                # starts a server, walks the lesson's scenario against it, stops it with SIGTERM
make check               # format check, lint with security rules, types, import rules, unit tests with coverage (no database)
make test-security       # one test per control of the threat model (needs make up)
make prove               # the lesson's "does each test fail without its control?": 10 guarding tests, 7 weaknesses
make test-integration    # the PostgreSQL adapters and the application role's privileges (needs make up)
make test-e2e            # a real server process with two workers, the scenario, SIGTERM, refusal to start (needs make up)
make test-all            # unit, integration, security and end-to-end
make audit               # known-vulnerability check of the locked dependencies
make sbom                # sbom.cdx.json (CycloneDX) for the runtime dependencies
make health              # exit 0 when the running server answers /readyz
make docker-run          # the image next to the database, healthy before it returns
make queries             # sql/003_queries.sql: visible notes, authorization inputs, sessions, audit summary
make down                # stops the containers and deletes their data
```

`make help` lists every target. Operational log lines are JSON on standard error. Edit and delete are JSON endpoints that need the session's CSRF token in an `X-CSRF-Token` header; [`demo_cli.py`](src/notes_app/interfaces/demo_cli.py) shows the exact requests.

## The SQL

Every statement the app runs is a bound parameter, and every script is a file under [sql/](sql/), run in this order:

| File | Kind | What it holds | Run by |
| --- | --- | --- | --- |
| [001_schema.sql](sql/001_schema.sql) | DDL | `users`, `notes`, `note_shares`, `sessions` with keys, indexes, constraints and comments; the `notes_app` role with no DDL rights | `make up` (`make db`) |
| [002_seed.sql](sql/002_seed.sql) | DML | three demo users (locked hash, so no credential is stored) and four notes, one shared | `make up` (`make db`) |
| [migrations/001_audit_events.sql](sql/migrations/001_audit_events.sql) | DDL (the audit-logging stretch) | `audit_events`, a trigger that refuses UPDATE and DELETE for every role, INSERT and SELECT for the app role only | `make up` |
| [migrations/002_login_failures.sql](sql/migrations/002_login_failures.sql) | DDL (the rate-limiting stretch) | the sign-in throttle's table, keyed by a digest | `make up` |
| [003_queries.sql](sql/003_queries.sql) | queries | what the notes page shows, the authorization inputs of one note, unshared notes, live sessions, audit summary, id-walking detector | `make queries` |
| [reset.sql](sql/reset.sql) | DML (outside the run order) | empty every table | `make reset-db`; the tests |

## Done when: the lesson's checklist and the proof for each line

| # | Done when (from the lesson) | Command | What proves it |
| --- | --- | --- | --- |
| 1 | Every trust boundary has at least one threat and the control that addresses it, and you name one threat you are accepting rather than fixing. | `make test` (the document test), read [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | The page draws the three boundaries (B1 browser and web server, B2 web server and service layer, B3 service layer and database), walks each through all six STRIDE letters and lists 21 threats with their controls. Five accepted risks (A1 to A5) are listed with reasons; A1 is the lesson's own example, an attacker with physical access to the database server. `tests/unit/test_threat_model_document.py` fails if a boundary has no threat, a "fixed" row has no linked test, or an accepted risk has no reason. |
| 2 | A test confirms the stored value is a salted hash, two users with the same password have different hashes, and no password appears in any log. | `make test-security` | [`test_passwords.py::test_passwords_are_salted_and_not_logged`](tests/security/test_passwords.py) signs up two users with one password, signs in, fails a sign-in on purpose, then reads the rows as the database owner: both start with `$argon2id$`, differ, and neither the password nor the wrong guess appears in any captured log line. |
| 3 | A test that saves a note containing a script tag and a SQL metacharacter shows the note renders as inert text and the database is unaffected. | `make test-security` | [`test_injection.py`](tests/security/test_injection.py): `test_hostile_content_is_stored_exactly_as_text` stores `<script>alert(1)</script> and a quote: ' OR '1'='1` and reads it back unchanged with the other tables untouched; `test_hostile_content_is_rendered_as_inert_text` finds `&lt;script&gt;` and no `<script>` in the page. |
| 4 | A test where user A requests user B's note by id gets a 403 or 404, for read, update and delete. | `make test-security` | [`test_authorization.py::test_user_a_cannot_read_update_or_delete_user_b_note`](tests/security/test_authorization.py): 404, 404, 404, and B's note is unchanged in the database. The choice (404 for what you cannot see, 403 for what you can see but not change) is [ADR 3](docs/adr/0003-not-found-for-notes-you-cannot-see.md) and applies to every route. |
| 5 | A test checks the cookie flags and headers on a response, and a state-changing request without the CSRF token is refused. | `make test-security` | [`test_session.py`](tests/security/test_session.py): `test_session_cookie_flags` (`__Host-` prefix, `HttpOnly`, `Secure`, `SameSite=Lax`, opaque 43-character value, only its hash stored), `test_security_headers_on_every_response` (six responses including a 404 and the stylesheet), `test_state_changing_request_without_csrf_token_is_refused` (POST, PATCH, DELETE and logout all 403, nothing created, changed or deleted). |
| 6 | Every "fixed" threat links to a passing test, and the accepted risks are listed with a reason. | `make test` | The verification table in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) names a test function for each of T1 to T21; the document test opens each file and checks the function exists. `make test-security` and `make test-integration` run them. |

### The tests fail without their controls (the lesson's "expected output")

The lesson runs the suite on a deliberately unhardened branch and shows the tests fail. Here the unhardened versions are in the code, behind seven settings that default to off and that the app refuses unless `APP_ENV=test` ([ADR 2](docs/adr/0002-deliberate-weaknesses.md)). `make prove` runs the guarding tests once with no weakness (all must pass), then once per weakness (the matching tests must fail):

```text
$ make prove
baseline, no weakness: 10 of 10 guarding tests pass
UNSAFE_WEAK_PASSWORD_HASH      test_passwords_are_salted_and_not_logged
                               -> FAILS without the control (proven)
UNSAFE_SQL_CONCATENATION       test_hostile_content_is_stored_exactly_as_text
                               -> FAILS without the control (proven)
UNSAFE_RAW_NOTE_OUTPUT         test_hostile_content_is_rendered_as_inert_text
                               -> FAILS without the control (proven)
UNSAFE_SKIP_OWNERSHIP_CHECK    test_user_a_cannot_read_update_or_delete_user_b_note
                               -> FAILS without the control (proven)
UNSAFE_SKIP_OWNERSHIP_CHECK    test_changing_the_id_in_the_url_reaches_no_note_of_another_user
                               -> FAILS without the control (proven)
UNSAFE_SKIP_OWNERSHIP_CHECK    test_a_user_the_note_is_shared_with_can_read_but_not_change_or_share_it
                               -> FAILS without the control (proven)
UNSAFE_WEAK_SESSION_COOKIE     test_session_cookie_flags
                               -> FAILS without the control (proven)
UNSAFE_SKIP_CSRF               test_state_changing_request_without_csrf_token_is_refused
                               -> FAILS without the control (proven)
UNSAFE_SKIP_CSRF               test_another_sessions_csrf_token_does_not_work
                               -> FAILS without the control (proven)
UNSAFE_SKIP_SECURITY_HEADERS   test_security_headers_on_every_response
                               -> FAILS without the control (proven)
10 of 10 guarding tests fail when their control is removed
```

The weakened code is plain: an unsalted SHA-256 hasher, an INSERT built with string concatenation, templates with encoding switched off, an access policy that allows everything, a cookie with no flags, no CSRF hook, no header hook. Each carries only what a test needs (a quote, a script tag, a foreign note id); there is no payload beyond that.

### The scenario, as `make demo` runs it

```text
$ make demo
scripts/demo.sh
healthy
 1. PASS  the server is ready
        /readyz -> 200
 2. PASS  the session cookie is opaque, HttpOnly, Secure, SameSite=Lax
        __Host-session=kesJqRWxR... (43 chars) Expires=Tue, 27 Oct 2026 07:58:10 GMT; Max-Age=28800; Secure; HttpOnly; Path=/; SameSite=Lax
 3. PASS  security headers are on the response
        missing: none
 4. PASS  hostile content is stored and rendered as inert text
        note 1: page shows the markup escaped
 5. PASS  another user gets 404 for read, update and delete
        GET, PATCH, DELETE -> [404, 404, 404]
 6. PASS  a state-changing request without the CSRF token is refused
        no token -> 403, wrong token -> 403
 7. PASS  repeated wrong passwords are throttled
        statuses [401, 401, 401, 401, 401, 429], Retry-After 887 s
 8. PASS  the old session id stops working after sign out
        GET /notes with the old cookie -> 401
8 of 8 checks passed
--- audit lines the server logged (ids and reasons only) ---
audit {"action": "csrf.rejected", "outcome": "refused", "user_id": 2, "ip": "127.0.0.1", "method": "DELETE", "path": "/notes/1"}
audit {"action": "login.failure", "outcome": "failure", "user_id": 3, "ip": "127.0.0.1"}
audit {"action": "login.failure", "outcome": "failure", "user_id": 3, "ip": "127.0.0.1"}
audit {"action": "login.failure", "outcome": "failure", "user_id": 3, "ip": "127.0.0.1"}
audit {"action": "login.failure", "outcome": "failure", "user_id": 3, "ip": "127.0.0.1"}
audit {"action": "login.failure", "outcome": "failure", "user_id": 3, "ip": "127.0.0.1"}
audit {"action": "login.throttled", "outcome": "refused", "user_id": null, "ip": "127.0.0.1"}
audit {"action": "logout", "outcome": "success", "user_id": 2, "ip": "127.0.0.1"}
--- shutdown ---
23:58:44 gunicorn.error: Handling signal: term
23:58:46 notes_app: database pool closed
23:58:46 notes_app: database pool closed
23:59:05 gunicorn.error: Shutting down: Master
```

## Stretch goals

| Stretch (from the lesson) | Built? |
| --- | --- |
| Add rate limiting on login and show lockout or backoff after repeated failures. | Yes. Failures per client address and username are counted in PostgreSQL (so every worker agrees); the sixth attempt gets 429 with `Retry-After`, even with the right password. Tests: `tests/security/test_authentication.py`, `tests/integration/test_repositories.py`. |
| Add audit logging for security events and check it can't be tampered with by a normal user. | Yes. Sign-up, sign-in, failures, throttling, sign-out, denied note access and rejected CSRF requests write a log line and a row; the app role can only insert and read, and a trigger refuses UPDATE and DELETE for every role. Tests: `tests/security/test_audit.py`. |
| Run a dependency and static analysis scanner and triage what it reports. | Yes. `make audit` (pip-audit on the lock file) and ruff's security rules (`S`, the Bandit rule set) run in `make lint` and in CI. Two deliberate findings are suppressed in place with their reason (the concatenated INSERT and the disabled encoding, both the weaknesses); nothing else is suppressed. |

## What is simplified for teaching

Only what the lesson scopes out:

- TLS is not terminated here: the app assumes a proxy does it (it sets `Secure` cookies and HSTS), and `make run` serves plain HTTP on the loopback address.
- No multi-factor authentication, no email verification, no password reset, no breached-password check (accepted risks A3 and A4).
- The pages are server-rendered HTML with no script; edit and delete are JSON endpoints rather than buttons, which keeps the content security policy at "no script at all".
- One PostgreSQL container with throwaway credentials from `.env`; the owner role and the application role are the two roles the lesson's "least privilege" needs.

## Project structure

```text
src/notes_app/
  domain/            value objects, validation, the access rule, the throttle rule, named errors.
                     Depends on nothing outside the standard library.
  application/       use cases (AccountService, SessionService, NoteService), the ports they need, the
                     production access policy. Depends on domain only.
  infrastructure/    PostgreSQL adapters (users, notes, sessions, audit, login failures), the argon2id hasher,
                     settings, JSON logging with redaction, the clock and token source.
                     weaknesses/ holds the seven deliberately weakened variants. Depends on application and domain.
  interfaces/        the Flask app (routes, cookie, CSRF hook, headers), the composition root, WSGI and gunicorn
                     wiring, the health and demo programs. Nothing depends on it.
sql/                 001_schema, 002_seed, 003_queries, reset, migrations/001 and 002.
tests/
  unit/              domain, application (with in-memory fakes), the HTTP layer over fakes, settings, logging,
                     the threat-model document. No services.
  integration/       the PostgreSQL adapters; the application role's privileges.
  security/          one test per control of the threat model (the lesson's tests/security/).
  e2e/               a real server process: the scenario, SIGTERM, refusal to start.
tech/                one note per technology, from zero, with an index (tech/README.md).
docs/                THREAT_MODEL.md and adr/ (sessions, deliberate weaknesses, 404 versus 403, throttle state).
scripts/             demo.sh, prove_controls.py.
docker-compose.yml   PostgreSQL 18, and the app under the `app` profile.     Dockerfile  the app as an image.
pyproject.toml       metadata and every tool's configuration (ruff, mypy, pytest, import-linter).
requirements*.lock   hash-pinned dependencies (runtime, and runtime plus development tools).
Makefile             the only commands a reader needs (make help).
```

The dependency rule (domain depends on nothing; application on domain; infrastructure and interfaces on both; nothing on interfaces) is enforced by `make lint` through import-linter. A second contract keeps Flask, werkzeug, Jinja, psycopg and argon2 out of `domain` and `application`.

## Author and license

Written by Sumit Srivastava. Released under the MIT License, see [LICENSE](LICENSE). Changes are in [CHANGELOG.md](CHANGELOG.md).
