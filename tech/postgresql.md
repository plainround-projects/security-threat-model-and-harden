# PostgreSQL 18

## What it is

PostgreSQL ("Postgres") is a **relational database server**: a long-running program that stores data in **tables** (rows and columns) on disk and answers questions asked in the language SQL (see `tech/sql.md`). Other programs connect to it over the network (default port 5432), prove who they are, and send statements. It guarantees that a group of changes either all happen or none do (a **transaction**), and it enforces rules you declare (types, uniqueness, links between tables).

## Why this repository uses it

The app has state that must be shared by every worker process and survive restarts: users, notes, shares, sessions, an audit trail and sign-in failures. PostgreSQL also gives the lesson three security tools that are not in the application code: a **least-privilege role** (the app's login can read and write rows but cannot change the schema), **constraints** that refuse bad data even if the code is wrong, and an **append-only trigger** that makes the audit table impossible to edit through SQL.

## Where it appears

| Path | What it does with PostgreSQL |
| --- | --- |
| `docker-compose.yml` | Runs `postgres:18` as the `postgres` service on host port 5471. |
| `sql/001_schema.sql` | Creates the `notes_app` role, four tables, indexes, grants. |
| `sql/migrations/001_audit_events.sql` | Audit table plus the trigger that blocks UPDATE and DELETE. |
| `sql/migrations/002_login_failures.sql` | The sign-in throttle's table. |
| `sql/002_seed.sql`, `003_queries.sql`, `reset.sql` | Demo data, read-only questions, and a table wipe for tests. |
| `src/notes_app/infrastructure/postgres/` | The Python adapters (via `tech/psycopg.md`). |
| `tests/integration/test_database.py` | Proves the role, constraints and trigger from outside the app. |

## How it works underneath

1. The server is one main process that starts a child process per connection. Data lives in files in its data directory; in this repository that is a Docker volume that `make down` deletes.
2. A **role** is an account. A role with `LOGIN` can connect. `NOSUPERUSER NOCREATEDB NOCREATEROLE` removes the powers that let a role bypass rules.
3. A **privilege** is a permission on an object (`SELECT`, `INSERT`, `UPDATE`, `DELETE` on a table). Without a `GRANT` a role can do nothing with it.
4. Each statement runs inside a transaction. The pool connection in Python opens one, and commits or rolls back at the end of a `with` block.
5. A **constraint** is a rule checked on every write: `NOT NULL`, `UNIQUE`, `CHECK (...)`, `PRIMARY KEY`, `REFERENCES` (a foreign key: this value must exist in another table).
6. A **trigger** is a function the server runs automatically before or after a write. If it raises an error, the write is cancelled.
7. An **index** is a sorted lookup structure that makes queries on those columns fast.

### Ideas you need first

- **A database server.** A program that stores data on disk in an organized way and answers questions about it. Other programs connect to it over the network (its default port is 5432), prove who they are, and send commands.
- **A table, a row and a column.** A table is like a spreadsheet sheet: each **column** has a name and a type (text, whole number, timestamp), and each **row** is one record. The `users` table has the columns `id`, `username`, `password_hash`, `created_at`; each registered person is one row.
- **A primary key and an index.** A **primary key** is the column (or columns) whose value identifies a row uniquely. An **index** is an extra sorted lookup structure the database keeps so it can find rows by certain columns quickly instead of reading the whole table.
- **A constraint.** A rule the database enforces on every write and refuses to break: `NOT NULL` (a value is required), `UNIQUE` (no two rows may share it), `CHECK (...)` (a condition must hold), `REFERENCES other (column)` (a **foreign key**: the value must exist in the other table).
- **A role and a privilege.** A role is a database account. A **privilege** is a permission on an object (such as `SELECT` to read, `INSERT` to add, `UPDATE`, `DELETE`). A role that has not been granted a privilege cannot use it.
- **A transaction.** A group of statements that either all take effect or none do. If anything fails halfway, the database undoes the earlier statements of the group (a **rollback**); if everything succeeds, the changes are made permanent (a **commit**).
- **A trigger.** A function the database runs automatically before or after a change to a table.
- **A connection.** One open channel between a client and the database server. Opening one is slow, so programs keep a few open and reuse them (a **pool**, `tech/psycopg.md`).

## Walkthrough of this repository's use

### Two roles: owner and application

The container starts with `POSTGRES_USER=notes_owner` (set in `.env`, default in `docker-compose.yml`). That role creates the schema. `001_schema.sql` then creates a second role:

```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'notes_app') THEN
        CREATE ROLE notes_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;
ALTER ROLE notes_app PASSWORD :'app_password';
```
`DO $$ ... $$` runs an anonymous block of the procedural language (PL/pgSQL). `$$` quotes the body without needing to escape single quotes. It creates the role only if it does not exist yet. `:'app_password'` is a `psql` variable, given on the command line by `make db` as `-v app_password="$(NOTES_DB_PASSWORD)"`; the `:'name'` form inserts it as a correctly quoted string, so the password is never written in a file.

The app connects as `notes_app` (see `Settings` in `infrastructure/settings.py`). The grants at the end of the file give it exactly what it needs:

```sql
GRANT USAGE ON SCHEMA public TO notes_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, notes, note_shares, sessions TO notes_app;
```
There is no `CREATE`, no `DROP`, no `ALTER`. So even a successful SQL injection through the app could not drop a table or change the schema. The integration tests check this by trying to.

### Constraints as a second line of defense

```sql
username      text        NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_]{3,32}$'),
password_hash text        NOT NULL CHECK (password_hash <> ''),
```
Even if validation in Python had a bug, the database refuses a bad username. `~` is "matches this regular expression". `UNIQUE` is what really decides a duplicate username: the repository inserts and catches the unique violation, which avoids a race between "check" and "insert".

```sql
owner_id   bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
title      text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
content    text        NOT NULL CHECK (char_length(content) <= 10000),
```
`REFERENCES users (id)` is a foreign key: a note cannot belong to a user that does not exist. `ON DELETE CASCADE` deletes a user's notes when the user goes. The length checks repeat the limits from `domain/validation.py`.

`id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY` makes the database number rows (1, 2, 3...). `ALWAYS` refuses attempts to supply an id by hand. `created_at timestamptz NOT NULL DEFAULT now()` stores a time with its time zone, filled by the server.

### Sessions store a hash, not the cookie

```sql
CREATE TABLE sessions (
    token_hash   text        PRIMARY KEY,
    user_id      bigint      REFERENCES users (id) ON DELETE CASCADE,
    csrf_token   text        NOT NULL,
    ...
```
The primary key is the SHA-256 of the cookie value. A stolen copy of this table does not contain any cookie a browser could send. `user_id` can be `NULL` for an anonymous session (the one that carries the sign-in form's CSRF token).

### The audit table and its trigger

```sql
CREATE FUNCTION audit_events_are_append_only() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% refused)', TG_OP USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_are_append_only();

GRANT SELECT, INSERT ON audit_events TO notes_app;
```
The function always raises an error. `TG_OP` is the operation that fired it (`UPDATE` or `DELETE`). The trigger runs it before any row is changed, for every role including the owner. And `notes_app` only has `SELECT, INSERT` on the table. Two layers: privileges for the app, a trigger for everyone. `user_id` has no foreign key on purpose: deleting a user must not edit history. `detail jsonb` holds structured extras (ids and reasons only, never credentials).

### The throttle table

`login_failures` stores `key_hash` (a SHA-256 of `client|username`, so neither is stored) and `attempted_at`. `GRANT SELECT, INSERT, DELETE` lets the app prune old rows. Because it is in the database, all workers share one count.

### Health and readiness

`Database.ping()` runs `SELECT 1`. The `/readyz` route returns 200 only if that works; the container health check calls it.

### Settings the app needs

Environment variables: `NOTES_DB_HOST`, `NOTES_DB_PORT` (5471 on the host, 5432 inside the Compose network), `NOTES_DB_NAME`, `NOTES_DB_USER` (default `notes_app`), `NOTES_DB_PASSWORD` (required), pool sizes. The password is never logged: `DatabaseSettings.password` is declared `field(repr=False)`.

### Every table, index, grant and migration

This lists everything the three schema files and the two migrations create.

**`users`** (`sql/001_schema.sql`). `id` is `bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY` (a large whole number the database fills with 1, 2, 3...; "always" refuses a value supplied by hand). `username` is `text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_]{3,32}$')` (`~` means "matches this regular expression"; `^` and `$` mean "the whole value"). `password_hash` is `text NOT NULL CHECK (password_hash <> '')`: `<>` means "not equal". It holds an Argon2 hash, or `!` for a seeded account that cannot sign in. `created_at` is `timestamptz NOT NULL DEFAULT now()`: a timestamp with its time zone, filled with the current time if not supplied. `COMMENT ON TABLE ...` stores a description inside the database.

**`notes`**. `id` as above. `owner_id bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE`: every note belongs to an existing user, and deleting a user deletes their notes (`CASCADE`). `title` has `CHECK (char_length(title) BETWEEN 1 AND 120)`; `content` has `CHECK (char_length(content) <= 10000)`; `created_at`, `updated_at` default to `now()`. Index `notes_owner_idx ON notes (owner_id, updated_at DESC)` speeds up "this owner's notes, newest first".

**`note_shares`**. Columns `note_id` and `user_id`, both foreign keys with `ON DELETE CASCADE`, and `PRIMARY KEY (note_id, user_id)`: a pair of columns is the key, so the same note cannot be shared twice with the same user. Index `note_shares_user_idx ON note_shares (user_id)` finds "notes shared with this user".

**`sessions`**. `token_hash text PRIMARY KEY` (the SHA-256 of the cookie value, so a stolen copy of the table contains nothing usable); `user_id bigint REFERENCES users (id) ON DELETE CASCADE` (may be null: an anonymous session); `csrf_token`; `created_at`, `last_seen_at`, `expires_at` (all `timestamptz NOT NULL`, set by the application). Index `sessions_expires_idx ON sessions (expires_at)` helps purging old sessions.

**Grants.** `GRANT USAGE ON SCHEMA public TO notes_app` lets the role see the tables' namespace (a **schema** is a named group of tables; `public` is the default one). `GRANT SELECT, INSERT, UPDATE, DELETE ON users, notes, note_shares, sessions TO notes_app` is every privilege the application needs on those four tables, and nothing else.

**`audit_events`** (`sql/migrations/001_audit_events.sql`). `id` as above; `occurred_at timestamptz DEFAULT now()`; `action` and `outcome` text; `user_id bigint` (deliberately **no** foreign key, so deleting a user never edits history); `ip text`; `detail jsonb NOT NULL DEFAULT '{}'::jsonb` (`jsonb` stores structured JSON efficiently; `'{}'::jsonb` is an empty object cast to that type). Two indexes on `(action, occurred_at DESC)` and `(user_id, occurred_at DESC)`. The function `audit_events_are_append_only()` is written in PL/pgSQL and always runs `RAISE EXCEPTION 'audit_events is append-only (% refused)', TG_OP USING ERRCODE = 'insufficient_privilege'` (`TG_OP` is "UPDATE" or "DELETE", whichever fired it). The trigger `audit_events_no_update_delete` is `BEFORE UPDATE OR DELETE ... FOR EACH ROW EXECUTE FUNCTION ...`, so every attempt to change or remove a row is refused for every role, the owner included. `GRANT SELECT, INSERT ON audit_events TO notes_app` (no update, no delete). The service layer writes it (`PostgresAuditLog`).

**`login_failures`** (`sql/migrations/002_login_failures.sql`). `key_hash` (a SHA-256 of `ip|username`), `attempted_at`; indexes on `(key_hash, attempted_at)` and `attempted_at`; granted `SELECT, INSERT, DELETE` (it needs to prune rows that aged out).

**`reset.sql`**: `TRUNCATE users, notes, note_shares, sessions, audit_events, login_failures RESTART IDENTITY CASCADE;` empties every table and restarts the id counters. `TRUNCATE` is not a row-level `DELETE`, so the audit trigger does not fire; it is run only by the owner, by tests and `make reset-db`. **`002_seed.sql`** inserts three users with the locked hash `!`, four notes and one share, so `make queries` has something to show.

**How `make up` and `make db` use them.** `make up` starts the container and asks `SELECT to_regclass('public.users') IS NOT NULL` (`to_regclass` returns the table's id or null). If the schema is already there it prints "schema already present"; otherwise `make db` runs `001_schema.sql` (with the app password as a `psql` variable), `002_seed.sql`, then each migration file in name order.

## Try it yourself

All of these need `make up` first (Docker running).

1. Open a SQL prompt as the owner:
   ```bash
   docker compose exec postgres psql -U notes_owner -d notes
   ```
   Then `\dt` lists `users`, `notes`, `note_shares`, `sessions`, `audit_events`, `login_failures`. Type `\q` to leave.
2. Ask the lesson's questions:
   ```bash
   make queries
   ```
   Expect result tables: visible notes for user 1, owner and shares of note 3, live sessions, audit summary.
3. Prove the audit table cannot be edited, even by the owner:
   ```bash
   docker compose exec -T postgres psql -U notes_owner -d notes -c "DELETE FROM audit_events"
   ```
   Expect `ERROR:  audit_events is append-only (DELETE refused)` (if the table has rows; with no rows the statement does nothing, so first run `make demo`).
4. See the app role's limits:
   ```bash
   docker compose exec -T -e PGPASSWORD="$NOTES_DB_PASSWORD" postgres psql -h 127.0.0.1 -U notes_app -d notes -c "DROP TABLE notes"
   ```
   Expect `ERROR:  must be owner of table notes`. (Export `NOTES_DB_PASSWORD` from your `.env` first, or run `set -a; . ./.env; set +a`.)

## Mistakes people make

- Connecting the application as the database owner or a superuser, so one injection owns everything. Here the app uses `notes_app`.
- Relying only on application checks. Constraints and triggers keep working when the code is wrong.
- Storing times without time zones. `timestamptz` is used.
- Deleting history by cascading from a user. The audit table has no foreign key.
- Putting the password in a file in the repository. It comes from `.env` through `-v app_password=...`.
- Checking "does this username exist?" and then inserting, which races. The unique constraint decides.

## Check yourself

1. What is the difference between the owner role and `notes_app`?
   *The owner can change the schema; `notes_app` can only read and write rows in listed tables.*
2. Why does the audit trigger fire even for the owner?
   *Triggers apply to every role; the owner is not exempt from the trigger function.*
3. What does `ON DELETE CASCADE` do?
   *Deleting the referenced row deletes the rows that point to it.*
4. Why is `sessions.token_hash` the primary key instead of the cookie value?
   *So a leaked table contains nothing usable as a cookie.*
5. Which table makes the sign-in throttle work across workers?
   *`login_failures`.*

## Further reading

- PostgreSQL 18 documentation: https://www.postgresql.org/docs/18/
- Constraints: https://www.postgresql.org/docs/18/ddl-constraints.html
- Privileges: https://www.postgresql.org/docs/18/ddl-priv.html
- Triggers: https://www.postgresql.org/docs/18/triggers.html
- Docker image: https://hub.docker.com/_/postgres
