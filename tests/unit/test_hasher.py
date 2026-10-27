from argon2 import PasswordHasher

from notes_app.infrastructure.argon2_hasher import Argon2PasswordHasher
from notes_app.infrastructure.weaknesses.unsalted_sha256_hasher import UnsaltedSha256Hasher

FAST = {"time_cost": 1, "memory_kib": 1024, "parallelism": 1}


def test_the_same_password_hashes_differently_each_time_and_verifies():
    hasher = Argon2PasswordHasher(**FAST)
    first, second = hasher.hash("correct horse battery staple"), hasher.hash("correct horse battery staple")
    assert first != second
    assert first.startswith("$argon2id$")
    assert hasher.verify("correct horse battery staple", first)
    assert not hasher.verify("another passphrase entirely", first)


def test_a_malformed_stored_value_never_verifies_and_always_needs_a_rehash():
    hasher = Argon2PasswordHasher(**FAST)
    assert not hasher.verify("anything", "not-a-hash")
    assert hasher.needs_rehash("not-a-hash")
    hasher.spend_equal_effort("anything")


def test_a_hash_made_with_weaker_parameters_needs_a_rehash():
    old = PasswordHasher(time_cost=1, memory_cost=512, parallelism=1).hash("pw")
    assert Argon2PasswordHasher(**FAST).needs_rehash(old)
    assert not Argon2PasswordHasher(**FAST).needs_rehash(Argon2PasswordHasher(**FAST).hash("pw"))


def test_the_deliberate_weakness_is_unsalted_so_equal_passwords_collide():
    weak = UnsaltedSha256Hasher()
    assert weak.hash("pw") == weak.hash("pw")
    assert weak.verify("pw", weak.hash("pw"))
    assert not weak.verify("other", weak.hash("pw"))
    assert not weak.needs_rehash("x")
    weak.spend_equal_effort("pw")
