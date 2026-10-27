-- reset.sql (DML, outside the run order): empty every table. Run as the owner role by `make reset-db` and by the tests.
TRUNCATE users, notes, note_shares, sessions, audit_events, login_failures RESTART IDENTITY CASCADE;
