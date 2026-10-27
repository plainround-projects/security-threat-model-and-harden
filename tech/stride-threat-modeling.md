# STRIDE threat modeling

## What it is

**Threat modeling** is a structured way of asking "what could go wrong with this system, and what are we doing about it?" before an attacker answers for you. **STRIDE** is a checklist of six kinds of threat, invented at Microsoft in the 1990s, so you do not forget a category:

| Letter | Threat | Breaks the property | Example in the notes app |
| --- | --- | --- | --- |
| **S**poofing | Pretending to be someone else | Authentication | Stealing or planting a session cookie |
| **T**ampering | Changing data or code you should not | Integrity | CSRF; SQL injection; editing the audit table |
| **R**epudiation | Doing something and denying it | Accountability | A sign-in nobody can attribute |
| **I**nformation disclosure | Reading what you should not | Confidentiality | Stored XSS; user enumeration; secrets in logs |
| **D**enial of service | Making the system unavailable | Availability | A huge request body |
| **E**levation of privilege | Doing more than you are allowed | Authorization | Reading another user's note by changing an id |

A **trust boundary** is a line in the system where data passes between parts that trust each other differently (browser to server, server to database). You walk every boundary through all six letters.

This is a method and a document format, not a software tool, but it is the backbone of the repository, so it has a note.

## Why this repository uses it

The lesson is "threat-model it, then harden it control by control". `docs/THREAT_MODEL.md` is the product of step one. Every later step (passwords, injection, authorization, sessions, audit) is the fix for a row in it. A unit test makes the document honest.

## Where it appears

| Path | What it does |
| --- | --- |
| `docs/THREAT_MODEL.md` | The diagram with three boundaries, the STRIDE grid, the verification table (T1 to T21), accepted risks. |
| `tests/unit/test_threat_model_document.py` | Parses the table and fails when a "fixed" row names a test that does not exist. |
| `tests/security/*.py` | One test per control. |
| `scripts/prove_controls.py` | Removes each control in turn and requires its tests to fail. |
| `src/notes_app/infrastructure/settings.py` (`Weaknesses`) | The `UNSAFE_*` switches that remove a control for the proof. |

## How it works underneath

1. **Draw** the system and mark the trust boundaries: B1 browser to web server, B2 web server to service layer, B3 service layer to database.
2. **Walk** each boundary through S, T, R, I, D, E and write down every threat (here T1 to T21).
3. For each threat pick a **control** (prevent, detect, or accept).
4. For each fixed threat, write the **test that proves the control**, and run it with the control removed to see it fail.
5. **Accept** what you will not fix, with a written reason (here, volumetric floods are left to infrastructure).

## Walkthrough of this repository's use

### The grid

The STRIDE table in `docs/THREAT_MODEL.md` has one row per boundary and one column per letter; each cell lists threat ids (for example B2 and Elevation: `T9 reading or changing another user's note, T12 reader editing a shared note`). A dash means "considered, nothing distinct here".

### The verification table

```
| T9 | B2 | Elevation of privilege | Reading, changing or deleting another user's note by changing the id in the URL | Authorization in `NoteService` on every request, answer looked up fresh; 404 for a note you may not see | `tests/security/test_authorization.py::test_user_a_cannot_read_update_or_delete_user_b_note` | fixed |
```
Seven columns: id, boundary, STRIDE letter, threat, control, proving test (file `::` function name), status. The pattern `file::function` is exactly how pytest names a test, so the table doubles as a command list.

### The document is tested

`test_threat_model_document.py` reads the markdown with a small parser (first table under the heading `## Verification note`) and asserts: the boundaries are exactly B1, B2, B3; there are at least 20 rows; every status is `fixed`; every row has a control; every proof names a test whose `def name(` really exists in that file; ids run T1, T2, ... without gaps; and at least one accepted risk exists with a reason. If someone renames a test, the document test fails.

### The proof by removal

`make prove` runs `scripts/prove_controls.py`. It first runs the guard tests with no weakness (all must pass), then for each `UNSAFE_*` switch runs only the tests that guard that control and requires them to fail. A test that still passes with its control removed proves nothing, and the script prints `STILL PASSES (not proven)` and exits 1. The result in this repository: 10 of 10 guarding tests fail when their control is removed.

## Try it yourself

1. Read the document: open `docs/THREAT_MODEL.md`; find T9 and the test it names.
2. Run the document test (no database):
   ```bash
   .venv/bin/pytest tests/unit/test_threat_model_document.py -v
   ```
   Expect 4 passed.
3. Break the document on purpose (do not commit): change a test name in the T9 row, run step 2 again. Expect a failure that says `...does not exist`. Undo with `git checkout docs/THREAT_MODEL.md`.
4. Run the full proof (needs `make up`):
   ```bash
   make prove
   ```
   Expect `baseline, no weakness: 10 of 10 guarding tests pass` and, at the end, `10 of 10 guarding tests fail when their control is removed`.

## Mistakes people make

- Listing threats with no tests, so the document rots. Here a test checks it.
- Writing only the threats you already fixed. The walk covers every letter at every boundary.
- Treating "accepted" as "ignored". Accepted risks carry a reason.
- Tests that cannot fail. The removal proof exists to catch them.

## Check yourself

1. What are the six STRIDE letters?
   *Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege.*
2. What is a trust boundary?
   *A line where data moves between parts that trust each other differently.*
3. Which property does repudiation break?
   *Accountability: you cannot show who did what.*
4. What does `file.py::test_name` mean?
   *The test function `test_name` in `file.py`, in pytest's naming.*
5. Why remove a control and rerun its tests?
   *To show the test really depends on the control; a test that still passes proves nothing.*

## Further reading

- OWASP Threat Modeling Process: https://owasp.org/www-community/Threat_Modeling_Process
- Microsoft, STRIDE: https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats
- Shostack, *Threat Modeling: Designing for Security* (book).
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
