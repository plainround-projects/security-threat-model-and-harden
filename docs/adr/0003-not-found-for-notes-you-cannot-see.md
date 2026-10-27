# 3. 404 for notes you cannot see, 403 for notes you can see but may not change

Date: 2026-10-27. Status: accepted.

## Context

The lesson asks for 403 or 404 when user A asks for user B's note, chosen on purpose and applied everywhere. A 403 confirms the id exists; a 404 does not.

## Decision

One rule, applied by the service for every action. If the requester has no access to the note, the answer is "not found" (404), the same answer as for an id that does not exist, with the same body. If the requester can read the note but the action needs more (a user the note is shared with trying to edit, delete or re-share it), the answer is 403, because they already know the note exists and a 404 would be a lie.

## Alternatives

- **403 for everything.** Lets anyone walk ids and learn which exist.
- **404 for everything.** Hides existence from outsiders but tells a reader "not found" about a note on their own list.

## Consequences

- Both denials are written to the audit trail (`note.access_denied`, with `no_access` or `read_only`), so an id walk is visible even though the response says nothing.
- Clients can tell "not yours" from "gone" only if they can already see the note.
