# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-27

### Added

- A notes application (sign up, sign in, notes, sharing with one other user) in four layers: `domain`, `application`, `infrastructure`, `interfaces`, with the dependency rule enforced by import-linter.
- The lesson's six steps: a STRIDE threat model with a verification note (`docs/THREAT_MODEL.md`) that a unit test checks against the suite; argon2id password hashing; parameterized SQL and output encoding; authorization in the service on every request; an opaque server-side session in a `__Host-` cookie with `HttpOnly`, `Secure` and `SameSite=Lax`, a CSRF token and security headers.
- The lesson's stretch goals: a PostgreSQL-backed sign-in throttle, an append-only audit trail (table, trigger and a role without UPDATE or DELETE), and a dependency audit plus static security rules (ruff `S`) in CI.
- SQL scripts: schema, seed, queries, reset, and two migrations (audit events, login failures).
- Seven deliberate weaknesses behind `UNSAFE_*` settings, accepted only under `APP_ENV=test`, and `make prove`, which removes each control in turn and shows its test fail.
- Structured JSON logging with redaction, health and readiness endpoints, graceful shutdown under gunicorn, a non-root Dockerfile, a hash-pinned lock file, a CycloneDX SBOM target and a CI workflow with every action pinned to a commit.
