# 2. Deliberate weaknesses behind named settings

Date: 2026-10-27. Status: accepted.

## Context

The lesson says a security test is only evidence when it fails on the unsafe version. It suggests a branch with the control reverted. A branch drifts from the code it is meant to mirror, and nobody runs it.

## Decision

Each control has a named weakened variant in the code: an unsalted SHA-256 hasher, an INSERT built by concatenation, templates that stop encoding, an access policy that allows everything, a cookie without flags, no CSRF hook, no security headers. A setting `UNSAFE_<NAME>` swaps the variant in at the composition root. `Settings` refuses any of them unless `APP_ENV=test`, and every setting defaults to off. `make prove` runs the guarding tests once per weakness and requires each to fail.

## Alternatives

- **A git branch with the controls reverted.** Drifts, needs a second checkout, and CI cannot run it cheaply.
- **Mocking the control away inside the test.** Proves the test works with a mock, not that the shipped control is what stops the attack.

## Consequences

- The weakened code is in the repository, under `infrastructure/weaknesses/` and two small branches in the HTTP layer. It is reachable only through settings that the application rejects outside tests, and it contains no exploit beyond what a test needs: a quote character, a script tag, a foreign note id.
- Ruff's security rules flag the concatenated statement and the disabled autoescape; each carries a `noqa` with the reason, so a new unexplained finding still fails the build.
- A new control comes with a weakness and a line in `scripts/prove_controls.py`, or it is not proven.
