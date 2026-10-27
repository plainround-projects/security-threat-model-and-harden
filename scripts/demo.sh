#!/usr/bin/env bash
# Start the server for the run, wait until it is ready, run the lesson's scenario, shut the server down with
# SIGTERM and show that it exited cleanly. Needs `make up` first. Called by `make demo`.
set -euo pipefail

PY=.venv/bin/python
LOG=$(mktemp)
.venv/bin/gunicorn -c python:notes_app.interfaces.gunicorn_conf "notes_app.interfaces.wsgi:build_app()" 2>"$LOG" &
SERVER=$!
trap 'kill -TERM "$SERVER" 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  if .venv/bin/notes-app-health >/dev/null 2>&1; then break; fi
  sleep 0.5
done
.venv/bin/notes-app-health

status=0
$PY -m notes_app.interfaces.demo_cli || status=$?

echo "--- audit lines the server logged (ids and reasons only) ---"
grep '"message":"audit"' "$LOG" | cut -c1-230 | tail -n 8 || true

kill -TERM "$SERVER"
wait "$SERVER" || true
trap - EXIT
echo "--- shutdown ---"
grep -E 'Handling signal|database pool closed|Shutting down' "$LOG" | cut -c1-160
rm -f "$LOG"
exit "$status"
