"""Prove each control by removing it: run the tests that guard it with the matching deliberate weakness switched on
and require every one of them to fail. A first run without any weakness requires them all to pass, so a failure
later means "this test notices the missing control", not "this test is broken".

    make prove          (needs make up)

The weaknesses are the UNSAFE_* settings; the app accepts them only under APP_ENV=test, which this script sets.
"""

from __future__ import annotations

import os
import subprocess
import sys

SECURITY = "tests/security"
# weakness setting -> the tests that must fail while it is on (the control it removes, as the threat model names it)
GUARDS: dict[str, tuple[str, ...]] = {
    "UNSAFE_WEAK_PASSWORD_HASH": (f"{SECURITY}/test_passwords.py::test_passwords_are_salted_and_not_logged",),
    "UNSAFE_SQL_CONCATENATION": (f"{SECURITY}/test_injection.py::test_hostile_content_is_stored_exactly_as_text",),
    "UNSAFE_RAW_NOTE_OUTPUT": (f"{SECURITY}/test_injection.py::test_hostile_content_is_rendered_as_inert_text",),
    "UNSAFE_SKIP_OWNERSHIP_CHECK": (
        f"{SECURITY}/test_authorization.py::test_user_a_cannot_read_update_or_delete_user_b_note",
        f"{SECURITY}/test_authorization.py::test_changing_the_id_in_the_url_reaches_no_note_of_another_user",
        f"{SECURITY}/test_authorization.py::test_a_user_the_note_is_shared_with_can_read_but_not_change_or_share_it",
    ),
    "UNSAFE_WEAK_SESSION_COOKIE": (f"{SECURITY}/test_session.py::test_session_cookie_flags",),
    "UNSAFE_SKIP_CSRF": (
        f"{SECURITY}/test_session.py::test_state_changing_request_without_csrf_token_is_refused",
        f"{SECURITY}/test_session.py::test_another_sessions_csrf_token_does_not_work",
    ),
    "UNSAFE_SKIP_SECURITY_HEADERS": (f"{SECURITY}/test_session.py::test_security_headers_on_every_response",),
}


def run_pytest(node_ids: tuple[str, ...], weakness: str | None) -> dict[str, str]:
    """Run the given tests and return {test name: passed | failed}, read from pytest's ``-rA`` summary lines."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("UNSAFE_")}
    env["APP_ENV"] = "test"
    if weakness:
        env[weakness] = "1"
    run = subprocess.run(
        [sys.executable, "-m", "pytest", *node_ids, "-q", "-p", "no:cacheprovider", "-rA", "--tb=no"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    outcomes = {}
    for line in run.stdout.splitlines():
        status, _, rest = line.partition(" ")
        if status in {"PASSED", "FAILED", "ERROR"} and "::" in rest:
            outcomes[rest.split("::")[-1].split(" ")[0]] = "passed" if status == "PASSED" else "failed"
    return outcomes


def main() -> int:
    """Print the table of weaknesses and verdicts; return 1 when a control is not proven."""
    every_guard = tuple(dict.fromkeys(node for nodes in GUARDS.values() for node in nodes))
    baseline = run_pytest(every_guard, None)
    broken = [name for name, outcome in baseline.items() if outcome != "passed"]
    print(f"baseline, no weakness: {len(baseline) - len(broken)} of {len(baseline)} guarding tests pass")
    if broken or len(baseline) != len(every_guard):
        print(f"FAIL: these must pass with every control in place: {broken or 'some tests did not run'}")
        return 1
    unproven = 0
    for weakness, nodes in GUARDS.items():
        outcomes = run_pytest(nodes, weakness)
        for node in nodes:
            name = node.split("::", 1)[1]
            verdict = (
                "FAILS without the control (proven)" if outcomes.get(name) == "failed" else "STILL PASSES (not proven)"
            )
            unproven += outcomes.get(name) != "failed"
            print(f"{weakness:<30} {name}\n{'':<30} -> {verdict}")
    total = sum(len(nodes) for nodes in GUARDS.values())
    print(f"{total - unproven} of {total} guarding tests fail when their control is removed")
    return 1 if unproven else 0


if __name__ == "__main__":
    sys.exit(main())
