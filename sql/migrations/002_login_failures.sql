-- migrations/002_login_failures.sql (DDL, the lesson's rate-limiting stretch): failed sign-ins per client and username.
-- Kept in the database so every worker process and replica enforces the same limit. The key is a SHA-256 digest of
-- "client address|username", so the table holds neither.

CREATE TABLE login_failures (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_hash     text        NOT NULL,
    attempted_at timestamptz NOT NULL
);
CREATE INDEX login_failures_key_idx ON login_failures (key_hash, attempted_at);
CREATE INDEX login_failures_age_idx ON login_failures (attempted_at);
COMMENT ON TABLE login_failures IS 'Failed sign-ins inside the throttle window; rows are pruned as they age out.';

GRANT SELECT, INSERT, DELETE ON login_failures TO notes_app;
