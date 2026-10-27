-- 002_seed.sql (DML): three demo users and a few notes for the queries in 003_queries.sql.
-- The seeded accounts have a locked hash ('!'), so they cannot sign in and no credential is stored here.
-- The demo (`make demo`) and the tests sign up their own users with generated passwords.

INSERT INTO users (username, password_hash) VALUES
    ('alice', '!'),
    ('bob',   '!'),
    ('carol', '!');

INSERT INTO notes (owner_id, title, content) VALUES
    ((SELECT id FROM users WHERE username = 'alice'), 'Groceries',      'Milk, eggs, bread'),
    ((SELECT id FROM users WHERE username = 'alice'), 'Reading list',   'Two books to finish this month'),
    ((SELECT id FROM users WHERE username = 'bob'),   'Trip plan',      'Train at 9, museum at 11'),
    ((SELECT id FROM users WHERE username = 'carol'), 'Draft',          'A note that is shared with nobody');

INSERT INTO note_shares (note_id, user_id) VALUES
    ((SELECT id FROM notes WHERE title = 'Trip plan'), (SELECT id FROM users WHERE username = 'alice'));
