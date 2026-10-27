# 1. Server-side sessions with an opaque id

Date: 2026-10-27. Status: accepted.

## Context

The app needs to remember who is signed in. The options are a signed cookie that carries the session (Flask's default), a JWT in a cookie, or an opaque random id that points at a row on the server. The threat model asks for protection against session theft and fixation, and the lesson's step 5 wants sign-out to mean something.

## Decision

The cookie holds a random 256-bit id. The server stores the SHA-256 of the id with the user, the CSRF token and the expiry times. The id is replaced at sign-in. The cookie is named `__Host-session` and carries `HttpOnly`, `Secure`, `SameSite=Lax` and `Path=/`.

## Alternatives

- **Signed cookie (Flask's `session`).** No lookup, but sign-out cannot revoke it, the contents sit in the browser, and one leaked signing key forges every session.
- **JWT in a cookie.** The same revocation problem plus parsing risks (algorithm confusion). Nothing here needs a token that other services verify.

## Consequences

- Sign-out, idle expiry and absolute expiry are real: deleting the row ends the session at once.
- A database read gives hashes, not usable ids.
- Every request does one session lookup; at this scale it is a primary-key read. A cache in front is the extension if it ever matters.
