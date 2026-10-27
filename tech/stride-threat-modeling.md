# STRIDE threat modeling

## What it is

**Threat modeling** is a structured way of asking "what could go wrong with this system, and what are we doing about it?" before an attacker answers for you. **STRIDE** is a checklist of six kinds of threat, invented at Microsoft in the 1990s, so you do not forget a category:

| Letter | Threat | Breaks the property | Example in the notes app |
| --- | --- | --- | --- |
| **S**poofing | Pretending to be someone else | Authentication | Stealing or planting a session cookie |
| **T**ampering | Changing data or code you should not | Integrity | CSRF; SQL injection; editing the audit table |
| **R**epudiation | Doing something and denying it | Accountability | A sign-in nobody can attribute |
| **I**nformation disclosure | Reading what you should not | Confidentiality | Stored XSS; user enumeration; secrets in logs |
| **D**enial of service | Making the system unavailable | Availability | A huge request body |
| **E**levation of privilege | Doing more than you are allowed | Authorization | Reading another user's note by changing an id |

A **trust boundary** is a line in the system where data passes between parts that trust each other differently (browser to server, server to database). You walk every boundary through all six letters.

This is a method and a document format, not a software tool, but it is the backbone of the repository, so it has a note.

## Why this repository uses it

The lesson is "threat-model it, then harden it control by control". `docs/THREAT_MODEL.md` is the product of step one. Every later step (passwords, injection, authorization, sessions, audit) is the fix for a row in it. A unit test makes the document honest.

## Where it appears

| Path | What it does |
| --- | --- |
| `docs/THREAT_MODEL.md` | The diagram with three boundaries, the STRIDE grid, the verification table (T1 to T21), accepted risks. |
| `tests/unit/test_threat_model_document.py` | Parses the table and fails when a "fixed" row names a test that does not exist. |
| `tests/security/*.py` | One test per control. |
| `scripts/prove_controls.py` | Removes each control in turn and requires its tests to fail. |
| `src/notes_app/infrastructure/settings.py` (`Weaknesses`) | The `UNSAFE_*` switches that remove a control for the proof. |

## How it works underneath

1. **Draw** the system and mark the trust boundaries: B1 browser to web server, B2 web server to service layer, B3 service layer to database.
2. **Walk** each boundary through S, T, R, I, D, E and write down every threat (here T1 to T21).
3. For each threat pick a **control** (prevent, detect, or accept).
4. For each fixed threat, write the **test that proves the control**, and run it with the control removed to see it fail.
5. **Accept** what you will not fix, with a written reason (here, volumetric floods are left to infrastructure).

### Ideas you need first

- **A threat.** Something that could go wrong on purpose: a person abusing the system.
- **A trust boundary.** A line where data passes between parts that you trust differently (browser to server, server to database). Most attacks cross one.
- **A control.** A measure that prevents, detects or limits a threat.
- **A proof.** A test that fails when the control is missing: the evidence that the control does its job.

## Walkthrough of this repository's use

### The grid

The STRIDE table in `docs/THREAT_MODEL.md` has one row per boundary and one column per letter; each cell lists threat ids (for example B2 and Elevation: `T9 reading or changing another user's note, T12 reader editing a shared note`). A dash means "considered, nothing distinct here".

### The verification table

```
| T9 | B2 | Elevation of privilege | Reading, changing or deleting another user's note by changing the id in the URL | Authorization in `NoteService` on every request, answer looked up fresh; 404 for a note you may not see | `tests/security/test_authorization.py::test_user_a_cannot_read_update_or_delete_user_b_note` | fixed |
```
Seven columns: id, boundary, STRIDE letter, threat, control, proving test (file `::` function name), status. The pattern `file::function` is exactly how pytest names a test, so the table doubles as a command list.

### The document is tested

`test_threat_model_document.py` reads the markdown with a small parser (first table under the heading `## Verification note`) and asserts: the boundaries are exactly B1, B2, B3; there are at least 20 rows; every status is `fixed`; every row has a control; every proof names a test whose `def name(` really exists in that file; ids run T1, T2, ... without gaps; and at least one accepted risk exists with a reason. If someone renames a test, the document test fails.

### The proof by removal

`make prove` runs `scripts/prove_controls.py`. It first runs the guard tests with no weakness (all must pass), then for each `UNSAFE_*` switch runs only the tests that guard that control and requires them to fail. A test that still passes with its control removed proves nothing, and the script prints `STILL PASSES (not proven)` and exits 1. The result in this repository: 10 of 10 guarding tests fail when their control is removed.

### Every threat, in plain words

The verification table in `docs/THREAT_MODEL.md` has 21 rows. Each says: who attacks, what they do, which control stops it, and which test proves it. (B1 is the browser-to-server boundary, B2 server-to-service, B3 service-to-database.)

| ID | In plain words | The control | The test that proves it |
| --- | --- | --- | --- |
| T1 | Someone steals a session: a script reads the cookie, or it travels over plain HTTP. | A random 256-bit id in a cookie that scripts cannot read, only sent over HTTPS, with the server storing only its hash. | `test_session_cookie_flags` |
| T2 | Session fixation: the attacker makes your browser use an id they know, then you sign in and they share your session. | A brand-new session id (and CSRF token) is issued at sign-in. | `test_the_session_id_changes_at_sign_in` |
| T3 | Guessing passwords for one account. | A failure throttle per client and username, a `Retry-After` header, and a deliberately slow password hash. | `test_repeated_failures_are_throttled_with_retry_after_and_audited` |
| T4 | CSRF: another website makes your browser send a request to this app with your cookie. | A per-session token required on every POST, PATCH and DELETE, plus `SameSite=Lax`. | `test_state_changing_request_without_csrf_token_is_refused` |
| T5 | Stored XSS: markup saved in a note runs as a script when someone else opens it. | The page encodes output, and a CSP allows no script at all. | `test_hostile_content_is_rendered_as_inert_text` |
| T6 | Clickjacking (the page framed invisibly), content-type sniffing, and the address leaking in `Referer`. | Security headers on every response. | `test_security_headers_on_every_response` |
| T7 | One huge request body wastes the server. | A 64 KiB body limit and length limits in validation. | `test_an_oversized_body_is_refused` |
| T8 | A sign-in or sign-out nobody can attribute afterwards. | An audit row and log line per sign-up, sign-in, failure, throttle and sign-out. | `test_sign_up_sign_in_failure_and_sign_out_are_audited` |
| T9 | Reading, changing or deleting another user's note by editing the id in the address. | The note service checks ownership or sharing on every request, looking the answer up fresh; a note you may not see answers 404. | `test_user_a_cannot_read_update_or_delete_user_b_note` |
| T10 | Mass assignment: sending an `owner_id` in the request body to take ownership. | The service takes the owner from the session, never from input. | `test_the_owner_in_the_request_body_is_ignored` |
| T11 | Walking ids leaves no trace. | A `note.access_denied` audit row with the note id and the reason. | `test_a_denied_note_access_writes_a_log_line_and_an_audit_row` |
| T12 | A user a note was shared with edits, deletes or re-shares it. | Sharing grants read only; other actions get 403. | `test_a_user_the_note_is_shared_with_can_read_but_not_change_or_share_it` |
| T13 | Telling "no such user" from "wrong password" (user enumeration). | One message, one status, equal hashing effort for unknown users. | `test_unknown_user_and_wrong_password_look_identical` |
| T14 | A password or note content ends up in a log file. | Bodies are never logged; the JSON formatter redacts sensitive field names. | `test_passwords_are_salted_and_not_logged` |
| T15 | SQL injection through a note, title or sign-in form. | Parameterized statements only; a quote is data. | `test_hostile_content_is_stored_exactly_as_text` |
| T16 | Passwords stored in plain text or with a fast hash. | Argon2id with a random salt per hash. | `test_passwords_are_salted_and_not_logged` |
| T17 | A read of the database yields live sessions. | Sessions are keyed by the SHA-256 of the cookie value. | `test_session_cookie_flags` |
| T18 | Someone rewrites the audit trail. | The application role has INSERT and SELECT only, and a trigger refuses UPDATE and DELETE for every role. | `test_the_application_role_cannot_change_or_delete_audit_rows` |
| T19 | A compromised app changes the database schema. | The app connects as a role with no schema-changing rights. | `test_the_application_role_cannot_change_the_schema` |
| T20 | Expired and anonymous sessions pile up. | Anonymous sessions live 15 minutes; expired rows are purged at every sign-in. | `test_purging_removes_only_expired_sessions` |
| T21 | A forged request goes unnoticed. | A `csrf.rejected` audit row. | `test_a_forged_request_is_audited` |

**Accepted risks (the document's second table).** A1: an attacker with physical access or root on the database server reads everything; an application cannot defend a host it does not control (disk encryption, network isolation and backups belong to the infrastructure layer). A2: a volumetric flood of requests; absorbing it is the job of the network edge (a CDN, a load balancer), the app only limits what one request can cost. A3: account takeover with a stolen or reused password and no second factor; multi-factor authentication is out of scope, and the next control to add. A4: passwords that appear in public breach lists are accepted if long enough; checking needs an external service or a large list. A5: plain HTTP between browser and app when no TLS terminator is in front; the app sets `Secure` cookies and HSTS and assumes a proxy ends HTTPS (`TRUSTED_PROXY_COUNT` tells it about the proxy).

**The weaknesses and their guards** (`scripts/prove_controls.py`): `UNSAFE_WEAK_PASSWORD_HASH` is guarded by `test_passwords_are_salted_and_not_logged`; `UNSAFE_SQL_CONCATENATION` by `test_hostile_content_is_stored_exactly_as_text`; `UNSAFE_RAW_NOTE_OUTPUT` by `test_hostile_content_is_rendered_as_inert_text`; `UNSAFE_SKIP_OWNERSHIP_CHECK` by three authorization tests; `UNSAFE_WEAK_SESSION_COOKIE` by `test_session_cookie_flags`; `UNSAFE_SKIP_CSRF` by two session tests; `UNSAFE_SKIP_SECURITY_HEADERS` by `test_security_headers_on_every_response`. Ten guarding tests in all.

## Try it yourself

1. Read the document: open `docs/THREAT_MODEL.md`; find T9 and the test it names.
2. Run the document test (no database):
   ```bash
   .venv/bin/pytest tests/unit/test_threat_model_document.py -v
   ```
   Expect 4 passed.
3. Break the document on purpose (do not commit): change a test name in the T9 row, run step 2 again. Expect a failure that says `...does not exist`. Undo with `git checkout docs/THREAT_MODEL.md`.
4. Run the full proof (needs `make up`):
   ```bash
   make prove
   ```
   Expect `baseline, no weakness: 10 of 10 guarding tests pass` and, at the end, `10 of 10 guarding tests fail when their control is removed`.

## Mistakes people make

- Listing threats with no tests, so the document rots. Here a test checks it.
- Writing only the threats you already fixed. The walk covers every letter at every boundary.
- Treating "accepted" as "ignored". Accepted risks carry a reason.
- Tests that cannot fail. The removal proof exists to catch them.

## Check yourself

1. What are the six STRIDE letters?
   *Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege.*
2. What is a trust boundary?
   *A line where data moves between parts that trust each other differently.*
3. Which property does repudiation break?
   *Accountability: you cannot show who did what.*
4. What does `file.py::test_name` mean?
   *The test function `test_name` in `file.py`, in pytest's naming.*
5. Why remove a control and rerun its tests?
   *To show the test really depends on the control; a test that still passes proves nothing.*

## Further reading

- OWASP Threat Modeling Process: https://owasp.org/www-community/Threat_Modeling_Process
- Microsoft, STRIDE: https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats
- Shostack, *Threat Modeling: Designing for Security* (book).
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
