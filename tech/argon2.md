# argon2-cffi and password hashing

## What it is

A **password hash** is a one-way scrambled form of a password that a server stores instead of the password. When you sign in, the server scrambles what you typed and compares. A good password hash is deliberately **slow** and **memory-hungry**, so an attacker who steals the database cannot try billions of guesses per second. **Argon2** won an international password-hashing competition in 2015; **argon2id** is the recommended variant. **argon2-cffi** (`argon2-cffi==25.1.0`, with `argon2-cffi-bindings==26.1.0`) is the Python package that calls the reference C implementation.

## Why this repository uses it

Threat T16 in `docs/THREAT_MODEL.md` is "passwords stored in plaintext or with a fast hash": the case where the database is stolen. If passwords were stored as plain text or fast hashes, one theft exposes every account (and every account where people reused the password). The lesson's control is argon2id with at least the OWASP minimum parameters, and a test that proves it is salted and never logged.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/notes_app/infrastructure/argon2_hasher.py` | `Argon2PasswordHasher`: hash, verify, needs-rehash, equal-effort. |
| `src/notes_app/infrastructure/settings.py` | The parameters and the check that production never goes below the minimum. |
| `src/notes_app/application/accounts.py` | Calls the hasher through the `PasswordHasher` port. |
| `src/notes_app/infrastructure/weaknesses/unsalted_sha256_hasher.py` | The bad version used by `make prove`. |
| `tests/security/test_passwords.py`, `tests/unit/test_hasher.py` | The proofs. |

## How it works underneath

1. To hash: choose a random **salt** (16 bytes here) so that two users with the same password get different hashes and precomputed tables ("rainbow tables") are useless. Run Argon2 with three cost knobs, then output one text string.
2. The three knobs: `time_cost` (how many passes over the memory), `memory_cost` (how many KiB of memory to fill: this is what makes graphics cards and special chips expensive for attackers), `parallelism` (lanes).
3. The output looks like this, and is stored in `users.password_hash`:
   ```
   $argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>
   ```
   Algorithm, version, parameters, salt and hash are all in the one string. To verify, the library reads the parameters from the stored string, hashes the typed password with the same salt, and compares.
4. Because parameters are stored with each hash, you can raise them later: old hashes still verify, and after a successful sign-in the app re-hashes with the new parameters (**rehash on login**).

### Ideas you need first

- **A hash function.** A function that turns any input into a short fixed-size fingerprint. The same input always gives the same fingerprint; you cannot work backwards from the fingerprint to the input. SHA-256 is one (it produces 256 bits, written as 64 hexadecimal characters); it is fast, which is good for fingerprints and bad for passwords.
- **A password hash.** A hash function built to be *slow* and *memory-hungry* on purpose, so a thief who steals the stored fingerprints can only test guesses slowly. Argon2 is one.
- **A salt.** Random bytes mixed into each hash so two users with the same password get different fingerprints, and so precomputed lookup tables are useless. The salt is stored next to the hash; it is not secret.
- **A cost parameter.** A setting that makes each hash take more time (`time_cost`, passes over memory) or more memory (`memory_cost`, in KiB), or more lanes (`parallelism`). Stored inside the hash string so old hashes still verify.
- **Timing.** A server that answers faster for some inputs tells an attacker something. Equal work for known and unknown users hides which usernames exist.

## Walkthrough of this repository's use

### Parameters

```python
ARGON2_MIN_TIME_COST = 2
ARGON2_MIN_MEMORY_KIB = 19_456
```
From `settings.py`: the OWASP Password Storage Cheat Sheet minimum for argon2id: 19 MiB of memory (19,456 KiB), 2 iterations, 1 lane. `ARGON2_PARALLELISM` defaults to 1. `Settings._validate` raises `ConfigError` if a non-test environment sets lower values, so the app refuses to start with weak parameters. Tests run with `time_cost=1, memory=1024` for speed (set in `tests/conftest.py`), allowed only under `APP_ENV=test`.

### The adapter

```python
self._argon2 = Argon2(time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism)
self._dummy_hash = self._argon2.hash("dummy-value-for-timing-equalization")
```
`Argon2` is `argon2.PasswordHasher`, which uses argon2id by default. The dummy hash is made once at start-up for the timing defense below.

```python
def verify(self, password: str, encoded: str) -> bool:
    try:
        return self._argon2.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
```
`argon2.PasswordHasher.verify(hash, password)` returns `True` or *raises* when the password is wrong; the argument order is hash first. The adapter turns every failure into `False`. Seeded accounts have the hash `!`, which raises `InvalidHashError` and so simply never matches.

```python
def needs_rehash(self, encoded: str) -> bool:
    try:
        return self._argon2.check_needs_rehash(encoded)
    except InvalidHashError:
        return True
```
True when the stored hash used weaker parameters than the current ones. In `AccountService.authenticate`, after a correct password: `if self._hasher.needs_rehash(user.password_hash): self._users.update_password_hash(user.id, self._hasher.hash(password))`.

### Equal effort for unknown users

```python
def spend_equal_effort(self, password: str) -> None:
    self.verify(password, self._dummy_hash)
```
If a username does not exist, the server would answer faster than for a real user (no hash to check), and the *time* would reveal which usernames exist. So the service does a full verification against the dummy hash and discards the result. The response is the same message too: `AuthenticationFailedError("invalid username or password")`.

### The weak version

```python
class UnsaltedSha256Hasher:
    def hash(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()
```
SHA-256 is a fine fingerprint but a poor password hash: it is fast and has no salt, so identical passwords give identical hashes. The test `test_passwords_are_salted_and_not_logged` signs up two users with the same password and asserts their stored hashes differ and start with `$argon2id$`. With the weakness on, it fails.

### Validation around passwords

`domain/validation.py` accepts 12 to 128 characters and no other rule (length is what matters, following NIST SP 800-63B). The upper bound exists because hashing time grows with input, so an unbounded password would be a denial-of-service lever.

## Try it yourself

1. Make a hash and read it:
   ```bash
   .venv/bin/python - <<'EOF'
   from argon2 import PasswordHasher
   h = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
   e = h.hash("correct horse battery")
   print(e)
   print(h.verify(e, "correct horse battery"))
   print(h.check_needs_rehash(e))
   try: h.verify(e, "wrong")
   except Exception as x: print(type(x).__name__)
   EOF
   ```
   Expect a string starting `$argon2id$v=19$m=19456,t=2,p=1$`, then `True`, `False`, `VerifyMismatchError`.
2. See that two hashes of one password differ:
   ```bash
   .venv/bin/python -c "
   from argon2 import PasswordHasher
   h = PasswordHasher()
   print(h.hash('same') == h.hash('same'))"
   ```
   Expect `False`.
3. Time it:
   ```bash
   .venv/bin/python -c "
   import time; from argon2 import PasswordHasher
   h = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1); t=time.perf_counter(); h.hash('x'); print(round(time.perf_counter()-t,3),'s')"
   ```
   Expect a small fraction of a second to a few tenths; that cost is the point.
4. Run the unit tests for the hasher: `.venv/bin/pytest tests/unit/test_hasher.py -q`. Expect all pass.

## Mistakes people make

- Storing passwords in plain text, or with a fast hash such as MD5 or SHA-256.
- No salt, or one salt for every user.
- Comparing hashes with `==` yourself. Use the library's `verify`.
- Different response or time for "no such user". Handled with the dummy hash and one message.
- Never upgrading parameters. `needs_rehash` makes upgrades automatic.
- Logging a password or its hash. The JSON formatter redacts any field whose name looks sensitive, and the test searches the captured logs for the password.

## Check yourself

1. Why is a salt random per user?
   *So equal passwords give different hashes and precomputed tables do not work.*
2. What is stored in `password_hash` besides the hash?
   *The algorithm, version, the three parameters and the salt.*
3. What does `spend_equal_effort` prevent?
   *Learning which usernames exist from how long a failed sign-in takes.*
4. What triggers a rehash?
   *A successful sign-in where the stored hash used weaker parameters than the current settings.*
5. Why is there a maximum password length?
   *Hash time grows with input; a huge password would be a cheap way to burn server time.*

## Further reading

- argon2-cffi 25.1 documentation: https://argon2-cffi.readthedocs.io/en/stable/
- Parameter choice: https://argon2-cffi.readthedocs.io/en/stable/parameters.html
- OWASP Password Storage Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- RFC 9106 (Argon2): https://www.rfc-editor.org/rfc/rfc9106
