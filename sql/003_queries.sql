-- 003_queries.sql: the queries the application runs, with the values bound as parameters in the code
-- (here shown with psql variables: `psql -v user_id=1 -v note_id=3`). `make queries` runs this file.

-- What the notes page shows: notes a user owns or has been given (PostgresNoteRepository.list_visible).
\set user_id 1
SELECT n.id, n.title, CASE WHEN n.owner_id = :user_id THEN 'owner' ELSE 'reader' END AS role
FROM notes n
WHERE n.owner_id = :user_id
   OR EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id AND s.user_id = :user_id)
ORDER BY n.updated_at DESC, n.id DESC;

-- The authorization inputs for one note: its owner and everyone it is shared with (the service reads both on every request).
\set note_id 3
SELECT owner_id FROM notes WHERE id = :note_id;
SELECT user_id FROM note_shares WHERE note_id = :note_id;

-- Notes nobody but their owner can see (no share rows).
SELECT n.id, n.title, u.username AS owner
FROM notes n JOIN users u ON u.id = n.owner_id
WHERE NOT EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id)
ORDER BY n.id;

-- Live sessions per user and how many anonymous sessions (sign-in forms) are waiting.
SELECT coalesce(u.username, '(anonymous)') AS who, count(*) AS sessions
FROM sessions s LEFT JOIN users u ON u.id = s.user_id
WHERE s.expires_at > now()
GROUP BY u.username ORDER BY sessions DESC;

-- Security events by action and outcome (the audit trail written by PostgresAuditLog).
SELECT action, outcome, count(*) AS events, max(occurred_at) AS latest
FROM audit_events
GROUP BY action, outcome ORDER BY events DESC;

-- Repeated access denials by one user: the signature of someone walking ids.
SELECT user_id, count(*) AS denials
FROM audit_events
WHERE action = 'note.access_denied'
GROUP BY user_id HAVING count(*) >= 3 ORDER BY denials DESC;
