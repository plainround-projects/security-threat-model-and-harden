import pytest

from notes_app.infrastructure.settings import ConfigError, Settings, Weaknesses

BASE = {"NOTES_DB_PASSWORD": "x"}


def test_defaults_are_the_hardened_ones():
    settings = Settings.from_environment(BASE)
    assert settings.app_env == "production"
    assert settings.weaknesses.enabled() == ()
    assert settings.argon2_time_cost >= 2
    assert settings.argon2_memory_kib >= 19_456
    assert settings.session.idle_seconds == 1800


def test_the_database_password_is_required_and_never_printed():
    with pytest.raises(ConfigError, match="NOTES_DB_PASSWORD"):
        Settings.from_environment({})
    settings = Settings.from_environment({"NOTES_DB_PASSWORD": "super-secret-value"})
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" in settings.database.conninfo()


def test_an_unknown_environment_name_is_refused():
    with pytest.raises(ConfigError, match="APP_ENV"):
        Settings.from_environment({**BASE, "APP_ENV": "staging"})


@pytest.mark.parametrize("name", ["APP_PORT", "NOTES_DB_PORT", "LOGIN_MAX_FAILURES"])
def test_a_non_numeric_or_too_small_integer_is_refused(name):
    with pytest.raises(ConfigError, match=name):
        Settings.from_environment({**BASE, name: "abc"})
    with pytest.raises(ConfigError, match=name):
        Settings.from_environment({**BASE, name: "0"})


def test_a_deliberate_weakness_is_refused_outside_the_test_environment():
    for app_env in ("production", "development"):
        with pytest.raises(ConfigError, match="only accepted when APP_ENV=test"):
            Settings.from_environment({**BASE, "APP_ENV": app_env, "UNSAFE_SKIP_CSRF": "1"})


def test_a_deliberate_weakness_is_accepted_in_the_test_environment():
    settings = Settings.from_environment(
        {**BASE, "APP_ENV": "test", "UNSAFE_SKIP_CSRF": "true", "UNSAFE_SKIP_ROTATION": "1"}
    )
    assert settings.weaknesses.enabled() == ("skip_csrf",)


def test_weakness_flags_read_only_known_truthy_values():
    weaknesses = Weaknesses.from_environment({"UNSAFE_SQL_CONCATENATION": "0", "UNSAFE_RAW_NOTE_OUTPUT": "yes"})
    assert weaknesses.enabled() == ("raw_note_output",)


def test_argon2_parameters_below_the_owasp_minimum_are_refused_outside_tests():
    with pytest.raises(ConfigError, match="argon2"):
        Settings.from_environment({**BASE, "ARGON2_MEMORY_KIB": "1024"})
    assert Settings.from_environment({**BASE, "APP_ENV": "test", "ARGON2_MEMORY_KIB": "1024"}).argon2_memory_kib == 1024


def test_inconsistent_pool_and_session_settings_are_refused():
    with pytest.raises(ConfigError, match="POOL"):
        Settings.from_environment({**BASE, "NOTES_DB_POOL_MIN": "9", "NOTES_DB_POOL_MAX": "2"})
    with pytest.raises(ConfigError, match="ANONYMOUS"):
        Settings.from_environment({**BASE, "ANONYMOUS_SESSION_SECONDS": "99999"})
