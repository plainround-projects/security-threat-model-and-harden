"""The lesson's scenario over real HTTP against a server process started the way production starts it."""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from notes_app.interfaces.demo_cli import run_scenario

pytestmark = pytest.mark.e2e
STARTUP_SECONDS = 180  # generous: a loaded CI runner or laptop boots two workers slowly
SERVE = [
    sys.executable,
    "-m",
    "gunicorn",
    "-c",
    "python:notes_app.interfaces.gunicorn_conf",
    "notes_app.interfaces.wsgi:build_app()",
]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _environment(port: int, **extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("UNSAFE_")}
    env.update({"APP_ENV": "development", "APP_HOST": "127.0.0.1", "APP_PORT": str(port), "WEB_CONCURRENCY": "2"})
    env.update(extra)
    return env


def _wait_until_ready(port: int, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        assert server.poll() is None, "the server exited before it was ready"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"the server did not become ready in {STARTUP_SECONDS} seconds")


@pytest.fixture
def server():
    port = _free_port()
    process = subprocess.Popen(SERVE, env=_environment(port), stderr=subprocess.PIPE, text=True)  # noqa: S603
    try:
        _wait_until_ready(port, process)
        yield port, process
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=60)


def test_the_scenario_passes_against_two_workers(server):
    port, _ = server
    steps = run_scenario("127.0.0.1", port)
    assert [step.name for step in steps if not step.passed] == []
    assert len(steps) >= 8


def test_sigterm_shuts_the_server_down_cleanly_and_closes_the_database_pool(server):
    _, process = server
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=60) == 0
    log = process.stderr.read()
    assert "Handling signal: term" in log
    assert log.count("database pool closed") == 2  # one per worker
    assert "Shutting down: Master" in log


def test_the_server_refuses_to_start_with_a_deliberate_weakness_outside_the_test_environment():
    process = subprocess.run(  # noqa: S603
        SERVE,
        env=_environment(_free_port(), UNSAFE_SKIP_CSRF="1"),
        capture_output=True,
        text=True,
        timeout=STARTUP_SECONDS,
        check=False,
    )
    assert process.returncode != 0
    assert "only accepted when APP_ENV=test" in process.stderr


def test_the_server_refuses_to_start_without_a_database_password():
    env = _environment(_free_port())
    env.pop("NOTES_DB_PASSWORD", None)
    process = subprocess.run(SERVE, env=env, capture_output=True, text=True, timeout=STARTUP_SECONDS, check=False)  # noqa: S603
    assert process.returncode != 0
    assert "NOTES_DB_PASSWORD is required" in process.stderr
