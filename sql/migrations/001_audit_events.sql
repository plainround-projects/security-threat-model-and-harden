-- migrations/001_audit_events.sql (DDL, the lesson's audit-logging stretch): an append-only audit trail.
-- The application role may insert and read rows, never update or delete them; a trigger refuses both for every
-- role, the owner included, so history cannot be rewritten through SQL.

CREATE TABLE audit_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    action      text        NOT NULL,
    outcome     text        NOT NULL,
    user_id     bigint,
    ip          text        NOT NULL,
    detail      jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_events_action_idx ON audit_events (action, occurred_at DESC);
CREATE INDEX audit_events_user_idx ON audit_events (user_id, occurred_at DESC);
COMMENT ON TABLE audit_events IS 'Append-only security events. user_id has no foreign key so deleting a user never edits history. detail holds ids and reasons only, never credentials or free text.';

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
