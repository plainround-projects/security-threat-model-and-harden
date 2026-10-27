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
