# SQL (the `sql/` files and the queries in Python)

## What it is

SQL (Structured Query Language) is the language you use to talk to a relational database. A statement is one instruction ending in `;`. There are three families:

- **DDL** (data definition): `CREATE TABLE`, `CREATE INDEX`, `GRANT`. It changes the *shape* of the database.
- **DML** (data manipulation): `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`. It changes the *rows*.
- **Queries**: `SELECT`. It reads rows.

This repository's files are PostgreSQL's dialect (see `tech/postgresql.md`).

## Why this repository uses it

SQL is where one of the lesson's top threats lives: **SQL injection**, which happens when a program builds a statement by pasting user text into it. The fix is to keep the statement and the data apart. Every statement the application runs is a fixed string with placeholders, and the values travel separately.

## Where it appears

| Path | Kind | What it does |
| --- | --- | --- |
| `sql/001_schema.sql` | DDL | Role, tables, indexes, grants. Run once as the owner by `make db`. |
| `sql/002_seed.sql` | DML | Three demo users with locked hashes and a few notes. |
| `sql/003_queries.sql` | queries | The questions the app asks, shown with `psql` variables. |
| `sql/migrations/*.sql` | DDL | Later additions: `audit_events`, `login_failures`. Applied in file-name order. |
| `sql/reset.sql` | DML | `TRUNCATE` every table; used by tests and `make reset-db`. |
| `src/notes_app/infrastructure/postgres/*.py` | queries | The statements the app runs, as Python strings with `%s` placeholders. |
| `src/notes_app/infrastructure/weaknesses/concatenated_notes.py` | the bad example | The same insert built by joining strings. Switched on only in test. |

## How it works underneath

1. The client (psql or the Python driver) sends the statement text to the server.
2. The server **parses** it into a tree, plans how to run it, executes it, and sends rows back.
3. If the statement and the values are sent separately (**parameter binding**), the server parses the statement *without* the values. A value can then only ever be data. It is never re-read as SQL.
4. If you paste the values into the text first, the server parses the combination, and a value like `x'); DROP TABLE users; --` becomes part of the program.

### Ideas you need first

- **SQL.** The language for asking a relational database for data and telling it to change data. A statement ends in `;`.
- **A statement and a query.** A statement is any command; a query is a statement that reads (`SELECT`).
- **A placeholder (parameter).** A marker such as `%s` in a statement where a value will be supplied separately. The database receives the statement and the values as two things, so a value can never change the statement's meaning.
- **A comment.** `--` starts a comment that runs to the end of the line.

## Walkthrough of this repository's use

### DDL: shape and rules

See `tech/postgresql.md` for the tables, constraints, grants and trigger. Points about the SQL itself:

- `--` starts a comment. Every file begins with a comment saying what it is and who runs it.
- `CREATE INDEX notes_owner_idx ON notes (owner_id, updated_at DESC);` builds a lookup for "this owner's notes, newest first".
- `COMMENT ON TABLE ... IS '...'` stores documentation inside the database. A doubled quote `''` inside a string is one literal quote.

### DML: seed and reset

```sql
INSERT INTO notes (owner_id, title, content) VALUES
    ((SELECT id FROM users WHERE username = 'alice'), 'Groceries', 'Milk, eggs, bread'),
```
A **subquery** in parentheses finds alice's generated id so the seed does not hard-code numbers. The seeded users have the hash `!`, which no password can match, so no credential is stored in the repository.

```sql
TRUNCATE users, notes, note_shares, sessions, audit_events, login_failures RESTART IDENTITY CASCADE;
```
`TRUNCATE` empties tables much faster than `DELETE`. `RESTART IDENTITY` resets the id counters. `CASCADE` includes tables that point at these. (It is not blocked by the audit trigger because the trigger is `BEFORE UPDATE OR DELETE`, not `TRUNCATE`; `reset.sql` runs as the owner and only for tests and local resets.)

### Queries in `003_queries.sql`

```sql
\set user_id 1
SELECT n.id, n.title, CASE WHEN n.owner_id = :user_id THEN 'owner' ELSE 'reader' END AS role
FROM notes n
WHERE n.owner_id = :user_id
   OR EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id AND s.user_id = :user_id)
ORDER BY n.updated_at DESC, n.id DESC;
```
`\set` is a psql command (not SQL) that defines a variable. `n` and `s` are table aliases. `CASE WHEN ... THEN ... ELSE ... END` is an if-expression. `EXISTS (subquery)` is true when the subquery returns any row: "a share row exists for this note and this user". `ORDER BY ... DESC` sorts newest first. The audit queries use `count(*)`, `GROUP BY` and `HAVING count(*) >= 3`: "users with three or more denials", the signature of someone walking ids.

### Parameterized statements in Python

```python
INSERT_NOTE = (
    "INSERT INTO notes (owner_id, title, content) VALUES (%s, %s, %s) "
    "RETURNING id, owner_id, title, content, created_at, updated_at"
)
...
row = connection.execute(INSERT_NOTE, (owner_id, title, content)).fetchone()
```
`%s` marks where a value goes. The values are passed as a separate tuple. `RETURNING` sends back the new row so no second query is needed. `LIST_VISIBLE` uses named placeholders `%(user_id)s` with a dictionary, because the same value appears three times. `INSERT_SHARE` ends in `ON CONFLICT DO NOTHING`, so sharing twice is not an error.

### The deliberately bad version

```python
statement = (
    "INSERT INTO notes (owner_id, title, content) VALUES ("
    + str(owner_id) + ", '" + title + "', '" + content
    + "') RETURNING id, owner_id, title, content, created_at, updated_at"
)
row = connection.execute(statement).fetchone()
```
A title such as `It's` breaks the statement (a syntax error), and a title built by an attacker can add statements. It exists only so `make prove` can show the injection test fail. It is reachable only with `APP_ENV=test` and `UNSAFE_SQL_CONCATENATION=1`.

### Every query in `sql/003_queries.sql`

Run by `make queries`. The first line of each block is `\set name value`, a `psql` command (not SQL) that defines a variable; `:user_id` then inserts it.

1. **Visible notes** (`\set user_id 1`): `SELECT n.id, n.title, CASE WHEN n.owner_id = :user_id THEN 'owner' ELSE 'reader' END AS role FROM notes n WHERE n.owner_id = :user_id OR EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id AND s.user_id = :user_id) ORDER BY n.updated_at DESC, n.id DESC;` `n` and `s` are short names (**aliases**) for the tables. `CASE WHEN ... END` is an if-else that produces the column `role`. `EXISTS (subquery)` is true when the inner query finds any row: "a share row exists for this note and this user". This is the same statement as `LIST_VISIBLE` in the Python code.
2. **Authorization inputs for one note** (`\set note_id 3`): `SELECT owner_id FROM notes WHERE id = :note_id;` and `SELECT user_id FROM note_shares WHERE note_id = :note_id;`: the two facts `NoteService` reads on every request.
3. **Notes nobody but the owner can see:** `SELECT n.id, n.title, u.username AS owner FROM notes n JOIN users u ON u.id = n.owner_id WHERE NOT EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id) ORDER BY n.id;` A **join** combines rows of two tables where the `ON` condition holds: each note is paired with its owner's row.
4. **Live sessions per user:** `SELECT coalesce(u.username, '(anonymous)') AS who, count(*) AS sessions FROM sessions s LEFT JOIN users u ON u.id = s.user_id WHERE s.expires_at > now() GROUP BY u.username ORDER BY sessions DESC;` A `LEFT JOIN` keeps sessions that have no user (anonymous ones); `coalesce(a, b)` returns the first value that is not null; `GROUP BY` collapses rows with the same user and `count(*)` counts them.
5. **Audit events by action and outcome:** `SELECT action, outcome, count(*) AS events, max(occurred_at) AS latest FROM audit_events GROUP BY action, outcome ORDER BY events DESC;`
6. **Id walking:** `SELECT user_id, count(*) AS denials FROM audit_events WHERE action = 'note.access_denied' GROUP BY user_id HAVING count(*) >= 3 ORDER BY denials DESC;` `HAVING` filters groups after counting; three or more denials by one user is the signature of someone trying ids.

`001_schema.sql`, `002_seed.sql`, `reset.sql` and the migrations are explained statement by statement in `tech/postgresql.md`.

### Line by line: `sql/001_schema.sql`

SQL is the language for talking to a relational database (`tech/sql.md`). This file is DDL (data definition language): it creates things. A line starting with `--` is a comment.

```sql
-- 001_schema.sql (DDL): the application's tables, keys, indexes, constraints and the least-privilege role.
-- Run as the owner role by `make db`:  psql -v app_password=... < sql/001_schema.sql
-- The application connects as `notes_app`, which can read and write rows but cannot change the schema.
```

The comments: the application's tables, keys, indexes, constraints and the least-privilege role; run as the owner role by `make db`; the app connects as `notes_app`, which can read and write rows but cannot change the schema.

```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'notes_app') THEN
        CREATE ROLE notes_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;
```

`DO $$ ... $$` runs a block of code once (`$$` quotes the body). If no role named `notes_app` exists in `pg_roles`, it creates one that can log in but is not a superuser and cannot create databases or roles. The check makes the file safe to repeat.

```sql
ALTER ROLE notes_app PASSWORD :'app_password';
```

`ALTER ROLE ... PASSWORD :'app_password'` sets the password from the psql variable given with `-v`, correctly quoted as a string.

```sql
CREATE TABLE users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      text        NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_]{3,32}$'),
    password_hash text        NOT NULL CHECK (password_hash <> ''),
    created_at    timestamptz NOT NULL DEFAULT now()
);
```

The `users` table. `id` is a number the database assigns (`GENERATED ALWAYS AS IDENTITY`) and the **primary key** (unique identifier of a row). `username` must be present, unique and match the pattern `^[a-z0-9_]{3,32}$` (`~` is the regular-expression match operator). `password_hash` must not be empty. `created_at` is a time with time zone filled in with `now()`.

```sql
COMMENT ON TABLE users IS 'Registered users. password_hash is an argon2id encoded hash (salt and parameters inside), or ! for a seeded account that cannot sign in.';
```

`COMMENT ON TABLE` stores documentation in the database: the hash is an argon2id value, or `!` for a seeded account that cannot sign in.

```sql
CREATE TABLE notes (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id   bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title      text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    content    text        NOT NULL CHECK (char_length(content) <= 10000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

The `notes` table. `owner_id` is a **foreign key** (`REFERENCES users (id)`: it must be an existing user) with `ON DELETE CASCADE` (deleting the user deletes their notes). The title is 1 to 120 characters, the content at most 10,000, and both timestamps default to now. These checks repeat the application's validation as a second line of defense.

```sql
CREATE INDEX notes_owner_idx ON notes (owner_id, updated_at DESC);
COMMENT ON TABLE notes IS 'A note and its owner. Whether a given user may see it is decided in the service layer on every request.';
```

`CREATE INDEX` builds a lookup structure on `(owner_id, updated_at DESC)` so listing a user's notes newest first is fast. A comment records that who may see a note is decided in the service layer on every request.

```sql
CREATE TABLE note_shares (
    note_id    bigint      NOT NULL REFERENCES notes (id) ON DELETE CASCADE,
    user_id    bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, user_id)
);
```

`note_shares` links a note to a user it is shared with. The primary key is the pair `(note_id, user_id)`, so one share per pair; both columns cascade on delete.

```sql
CREATE INDEX note_shares_user_idx ON note_shares (user_id);
COMMENT ON TABLE note_shares IS 'A note shared read-only with one other user, by user id.';
```

An index on `user_id` (to find what is shared with a user) and a comment.

```sql
CREATE TABLE sessions (
    token_hash   text        PRIMARY KEY,
    user_id      bigint      REFERENCES users (id) ON DELETE CASCADE,
    csrf_token   text        NOT NULL,
    created_at   timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    expires_at   timestamptz NOT NULL
);
```

`sessions`: `token_hash` is the primary key (the stored SHA-256 of the cookie value), `user_id` may be null for an anonymous session, `csrf_token` is the token for that session, and three times.

```sql
CREATE INDEX sessions_expires_idx ON sessions (expires_at);
COMMENT ON TABLE sessions IS 'Server-side sessions keyed by the SHA-256 of the cookie value, so a database read yields no usable session. user_id is null for the anonymous session that carries the sign-in form''s CSRF token.';
```

An index on `expires_at` so purging expired sessions is fast, and a comment (the doubled quote `''` inside a text is one quote).

```sql
GRANT USAGE ON SCHEMA public TO notes_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, notes, note_shares, sessions TO notes_app;
```

`GRANT USAGE ON SCHEMA public` lets the role look inside the schema; `GRANT SELECT, INSERT, UPDATE, DELETE` on the four tables lets it read and write rows. It cannot create, alter or drop tables.

### Line by line: `sql/002_seed.sql`

```sql
-- 002_seed.sql (DML): three demo users and a few notes for the queries in 003_queries.sql.
-- The seeded accounts have a locked hash ('!'), so they cannot sign in and no credential is stored here.
-- The demo (`make demo`) and the tests sign up their own users with generated passwords.
```

The comments: three demo users and a few notes for the queries file. The seeded accounts have a locked hash (`!`), which no password can match, so they cannot sign in and no credential is stored.

```sql
INSERT INTO users (username, password_hash) VALUES
    ('alice', '!'),
    ('bob',   '!'),
    ('carol', '!');
```

Inserts three users in one statement (several rows separated by commas).

```sql
INSERT INTO notes (owner_id, title, content) VALUES
    ((SELECT id FROM users WHERE username = 'alice'), 'Groceries',      'Milk, eggs, bread'),
    ((SELECT id FROM users WHERE username = 'alice'), 'Reading list',   'Two books to finish this month'),
    ((SELECT id FROM users WHERE username = 'bob'),   'Trip plan',      'Train at 9, museum at 11'),
    ((SELECT id FROM users WHERE username = 'carol'), 'Draft',          'A note that is shared with nobody');
```

Inserts four notes. The owner id is found with a subquery `(SELECT id FROM users WHERE username = 'alice')`, so the file does not depend on the numbers the database assigned.

```sql
INSERT INTO note_shares (note_id, user_id) VALUES
    ((SELECT id FROM notes WHERE title = 'Trip plan'), (SELECT id FROM users WHERE username = 'alice'));
```

Shares the 'Trip plan' note (Bob's) with Alice.

### Line by line: `sql/003_queries.sql`

```sql
-- 003_queries.sql: the queries the application runs, with the values bound as parameters in the code
-- (here shown with psql variables: `psql -v user_id=1 -v note_id=3`). `make queries` runs this file.
```

The comments: these are the queries the application runs, shown with psql variables instead of bound parameters. `make queries` runs the file.

```sql
-- What the notes page shows: notes a user owns or has been given (PostgresNoteRepository.list_visible).
\set user_id 1
SELECT n.id, n.title, CASE WHEN n.owner_id = :user_id THEN 'owner' ELSE 'reader' END AS role
FROM notes n
WHERE n.owner_id = :user_id
   OR EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id AND s.user_id = :user_id)
ORDER BY n.updated_at DESC, n.id DESC;
```

`\set user_id 1` is a psql command (not SQL) that sets a variable; `:user_id` inserts it. The query lists the notes a user owns or has been given: a `CASE` gives `owner` or `reader`; `EXISTS (subquery)` is true if a share row exists; `ORDER BY` puts the most recently updated first.

```sql
-- The authorization inputs for one note: its owner and everyone it is shared with (the service reads both on every request).
\set note_id 3
SELECT owner_id FROM notes WHERE id = :note_id;
SELECT user_id FROM note_shares WHERE note_id = :note_id;
```

The two inputs of an authorization decision: the note's owner and everyone it is shared with.

```sql
-- Notes nobody but their owner can see (no share rows).
SELECT n.id, n.title, u.username AS owner
FROM notes n JOIN users u ON u.id = n.owner_id
WHERE NOT EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id)
ORDER BY n.id;
```

Notes nobody but the owner can see: `NOT EXISTS` finds notes with no share row; `JOIN` attaches the owner's name.

```sql
-- Live sessions per user and how many anonymous sessions (sign-in forms) are waiting.
SELECT coalesce(u.username, '(anonymous)') AS who, count(*) AS sessions
FROM sessions s LEFT JOIN users u ON u.id = s.user_id
WHERE s.expires_at > now()
GROUP BY u.username ORDER BY sessions DESC;
```

Live sessions per user: `LEFT JOIN` keeps sessions with no user, `coalesce(u.username, '(anonymous)')` replaces the missing name, `count(*)` counts, `GROUP BY` groups by username and only unexpired sessions count.

```sql
-- Security events by action and outcome (the audit trail written by PostgresAuditLog).
SELECT action, outcome, count(*) AS events, max(occurred_at) AS latest
FROM audit_events
GROUP BY action, outcome ORDER BY events DESC;
```

Security events by action and outcome with the count and the latest time.

```sql
-- Repeated access denials by one user: the signature of someone walking ids.
SELECT user_id, count(*) AS denials
FROM audit_events
WHERE action = 'note.access_denied'
GROUP BY user_id HAVING count(*) >= 3 ORDER BY denials DESC;
```

Users with three or more denied accesses (`HAVING count(*) >= 3` filters after grouping): the signature of someone walking ids.

### Line by line: `sql/reset.sql`

```sql
-- reset.sql (DML, outside the run order): empty every table. Run as the owner role by `make reset-db` and by the tests.
TRUNCATE users, notes, note_shares, sessions, audit_events, login_failures RESTART IDENTITY CASCADE;
```

`TRUNCATE` empties the tables quickly; `RESTART IDENTITY` resets the id counters and `CASCADE` also empties tables that depend on them. Run as the owner by `make reset-db` and by the tests.

### Line by line: `sql/migrations/001_audit_events.sql`

```sql
-- migrations/001_audit_events.sql (DDL, the lesson's audit-logging stretch): an append-only audit trail.
-- The application role may insert and read rows, never update or delete them; a trigger refuses both for every
-- role, the owner included, so history cannot be rewritten through SQL.
```

The comments: an append-only audit trail. The app role may insert and read rows, never update or delete them; a trigger refuses both for every role, the owner included.

```sql
CREATE TABLE audit_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    action      text        NOT NULL,
    outcome     text        NOT NULL,
    user_id     bigint,
    ip          text        NOT NULL,
    detail      jsonb       NOT NULL DEFAULT '{}'::jsonb
);
```

The table: an id, the time, action, outcome, an optional user id, the IP and `detail` as `jsonb` (JSON stored in a binary form PostgreSQL can query) defaulting to an empty object.

```sql
CREATE INDEX audit_events_action_idx ON audit_events (action, occurred_at DESC);
CREATE INDEX audit_events_user_idx ON audit_events (user_id, occurred_at DESC);
```

Two indexes for looking up by action and by user, newest first.

```sql
COMMENT ON TABLE audit_events IS 'Append-only security events. user_id has no foreign key so deleting a user never edits history. detail holds ids and reasons only, never credentials or free text.';
```

The comment says `user_id` has no foreign key so deleting a user never edits history.

```sql
CREATE FUNCTION audit_events_are_append_only() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% refused)', TG_OP USING ERRCODE = 'insufficient_privilege';
END
$$;
```

`CREATE FUNCTION ... RETURNS trigger LANGUAGE plpgsql` defines a function in PostgreSQL's procedural language. Its body raises an exception with the operation name (`TG_OP`) and the error code `insufficient_privilege`.

```sql
CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_are_append_only();
```

`CREATE TRIGGER` runs that function before every update or delete on every row. The trigger works for every role, including the table's owner.

```sql
GRANT SELECT, INSERT ON audit_events TO notes_app;
```

The app role gets `SELECT` and `INSERT` only.

### Line by line: `sql/migrations/002_login_failures.sql`

```sql
-- migrations/002_login_failures.sql (DDL, the lesson's rate-limiting stretch): failed sign-ins per client and username.
-- Kept in the database so every worker process and replica enforces the same limit. The key is a SHA-256 digest of
-- "client address|username", so the table holds neither.
```

The comments: failed sign-ins per client and username, kept in the database so every worker and replica enforces the same limit. The key is a SHA-256 digest of `client address|username`, so the table holds neither.

```sql
CREATE TABLE login_failures (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_hash     text        NOT NULL,
    attempted_at timestamptz NOT NULL
);
```

The table: an id, the key digest and the time of the attempt.

```sql
CREATE INDEX login_failures_key_idx ON login_failures (key_hash, attempted_at);
CREATE INDEX login_failures_age_idx ON login_failures (attempted_at);
```

Two indexes: by key and time (for the count in the window) and by time (for pruning).

```sql
COMMENT ON TABLE login_failures IS 'Failed sign-ins inside the throttle window; rows are pruned as they age out.';
```

A comment on the table.

```sql
GRANT SELECT, INSERT, DELETE ON login_failures TO notes_app;
```

The app role may select, insert and delete, but not update.

## Try it yourself

1. With `make up` done, run the lesson's queries: `make queries`. Expect several small tables.
2. See what injection would do, with no database: 
   ```bash
   .venv/bin/python - <<'EOF'
   title = "x', 'y'); DROP TABLE users; --"
   print("INSERT INTO notes (owner_id, title, content) VALUES (1, '" + title + "', 'c')")
   EOF
   ```
   Expect a line containing a second statement, `DROP TABLE users;`.
3. Check that real hostile text is stored as text (needs `make up`):
   ```bash
   .venv/bin/pytest tests/security/test_injection.py::test_hostile_content_is_stored_exactly_as_text -q
   ```
   Expect `1 passed`.
4. Run the same test with the weakness on:
   ```bash
   APP_ENV=test UNSAFE_SQL_CONCATENATION=1 .venv/bin/pytest tests/security/test_injection.py::test_hostile_content_is_stored_exactly_as_text -q
   ```
   Expect `1 failed`.

## Mistakes people make

- Building statements with f-strings or `+`. Here only the one test-only class does, and ruff's `S608` rule would flag it (it carries a `noqa` with the reason).
- Escaping by hand instead of binding. Binding is the only reliable fix.
- Putting the percent sign in a literal: with `%s` placeholders, a literal `%` in SQL must be written `%%`. None of the app's statements need one.
- Forgetting the `WHERE` on `UPDATE` or `DELETE`. Each statement here has one.
- Using `SELECT *`. Statements name their columns, so a new column never changes what the code reads.

## Check yourself

1. What is the difference between DDL and DML?
   *DDL changes the structure (tables, grants); DML changes rows.*
2. Why do values travel separately from the statement?
   *The server parses the statement without them, so they can only be data.*
3. What does `RETURNING` do?
   *Returns the inserted or updated row(s) from the same statement.*
4. What does `ON CONFLICT DO NOTHING` do on `note_shares`?
   *A duplicate (note, user) pair is ignored instead of raising an error.*
5. Why is the seeded hash `!`?
   *No password can match it, so seeded accounts cannot sign in and no credential is stored.*

## Further reading

- PostgreSQL 18 SQL commands: https://www.postgresql.org/docs/18/sql-commands.html
- `INSERT ... ON CONFLICT`: https://www.postgresql.org/docs/18/sql-insert.html
- `psql` variables: https://www.postgresql.org/docs/18/app-psql.html#APP-PSQL-VARIABLES
- OWASP SQL injection prevention: https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
