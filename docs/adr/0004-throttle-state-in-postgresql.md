# 4. Sign-in throttle state in PostgreSQL

Date: 2026-10-27. Status: accepted.

## Context

The first version kept failure timestamps in a dictionary inside the process. Under gunicorn with two workers, each worker had its own count, so the demo's sixth wrong password did not trip the limit: six attempts split across two workers. With N workers the limit is multiplied by N, and a restart forgets it.

## Decision

Failures go in a table (`login_failures`), keyed by the SHA-256 of `client address|username` so the table holds neither. The rule (how many in which window, when to retry) is a pure function in the domain; the adapter only reads and writes timestamps. Rows are pruned as they leave the window.

## Alternatives

- **Redis.** The usual production answer and faster, but one more container for a counter the database already serves.
- **In memory with one worker.** Correct only until someone raises the worker count.

## Consequences

- One extra indexed read per sign-in attempt and one write per failure.
- The limit holds across workers and replicas, and survives restarts.
- Keying by address and username lets an attacker lock one victim out only from their own address; it does not stop a distributed guess across many addresses, which is a job for the edge (accepted risk A2 and A3 in the threat model).
