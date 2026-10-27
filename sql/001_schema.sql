-- 001_schema.sql (DDL): the application's tables, keys, indexes, constraints and the least-privilege role.
-- Run as the owner role by `make db`:  psql -v app_password=... < sql/001_schema.sql
-- The application connects as `notes_app`, which can read and write rows but cannot change the schema.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'notes_app') THEN
        CREATE ROLE notes_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;
ALTER ROLE notes_app PASSWORD :'app_password';

CREATE TABLE users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      text        NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_]{3,32}$'),
    password_hash text        NOT NULL CHECK (password_hash <> ''),
    created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE users IS 'Registered users. password_hash is an argon2id encoded hash (salt and parameters inside), or ! for a seeded account that cannot sign in.';

CREATE TABLE notes (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id   bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title      text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    content    text        NOT NULL CHECK (char_length(content) <= 10000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notes_owner_idx ON notes (owner_id, updated_at DESC);
COMMENT ON TABLE notes IS 'A note and its owner. Whether a given user may see it is decided in the service layer on every request.';

CREATE TABLE note_shares (
    note_id    bigint      NOT NULL REFERENCES notes (id) ON DELETE CASCADE,
    user_id    bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, user_id)
);
CREATE INDEX note_shares_user_idx ON note_shares (user_id);
COMMENT ON TABLE note_shares IS 'A note shared read-only with one other user, by user id.';

CREATE TABLE sessions (
    token_hash   text        PRIMARY KEY,
    user_id      bigint      REFERENCES users (id) ON DELETE CASCADE,
    csrf_token   text        NOT NULL,
    created_at   timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    expires_at   timestamptz NOT NULL
);
CREATE INDEX sessions_expires_idx ON sessions (expires_at);
COMMENT ON TABLE sessions IS 'Server-side sessions keyed by the SHA-256 of the cookie value, so a database read yields no usable session. user_id is null for the anonymous session that carries the sign-in form''s CSRF token.';

GRANT USAGE ON SCHEMA public TO notes_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, notes, note_shares, sessions TO notes_app;
