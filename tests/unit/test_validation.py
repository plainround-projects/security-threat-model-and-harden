import pytest

from notes_app.domain.errors import InvalidInputError
from notes_app.domain.validation import (
    CONTENT_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    validate_note_content,
    validate_note_title,
    validate_password,
    validate_username,
)


def test_username_is_lowercased_and_trimmed():
    assert validate_username("  Alice_01 ") == "alice_01"


@pytest.mark.parametrize("raw", ["ab", "a" * 33, "has space", "semi;colon", "quote'", "ünicode", ""])
def test_username_outside_the_allow_list_is_refused(raw):
    with pytest.raises(InvalidInputError) as error:
        validate_username(raw)
    assert error.value.field == "username"


@pytest.mark.parametrize("raw", ["short", "x" * 129, ""])
def test_password_length_bounds_are_enforced(raw):
    with pytest.raises(InvalidInputError):
        validate_password(raw)


def test_a_long_passphrase_with_spaces_is_accepted_unchanged():
    passphrase = "correct horse battery staple"
    assert validate_password(passphrase) == passphrase


def test_title_is_trimmed_and_must_be_one_line():
    assert validate_note_title("  Plan  ") == "Plan"
    for bad in ["", "   ", "x" * (TITLE_MAX_LENGTH + 1), "two\nlines", "carriage\rreturn", "nul\x00"]:
        with pytest.raises(InvalidInputError):
            validate_note_title(bad)


def test_content_keeps_markup_because_output_encoding_handles_it():
    hostile = "<script>alert(1)</script> and a quote: ' OR '1'='1"
    assert validate_note_content(hostile) == hostile


def test_content_refuses_nul_and_oversize():
    with pytest.raises(InvalidInputError):
        validate_note_content("a\x00b")
    with pytest.raises(InvalidInputError):
        validate_note_content("x" * (CONTENT_MAX_LENGTH + 1))
