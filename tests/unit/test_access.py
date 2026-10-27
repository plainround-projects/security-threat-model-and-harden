from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.domain.access import Access, access_to_note


def test_owner_has_write_access():
    assert access_to_note(owner_id=1, shared_with=set(), user_id=1) is Access.WRITE


def test_user_the_note_is_shared_with_can_only_read():
    assert access_to_note(owner_id=1, shared_with={2}, user_id=2) is Access.READ


def test_everyone_else_has_no_access():
    assert access_to_note(owner_id=1, shared_with={2}, user_id=3) is Access.NONE


def test_access_levels_are_ordered_so_write_includes_read():
    assert Access.WRITE > Access.READ > Access.NONE


def test_the_production_policy_is_the_domain_rule():
    policy = OwnerOrSharedPolicy()
    assert policy.access(owner_id=1, shared_with=frozenset({2}), user_id=2) is Access.READ
