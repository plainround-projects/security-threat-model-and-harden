"""Configuration from the environment (twelve-factor), validated once at start-up."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Literal

from notes_app.application.sessions import SessionPolicy

AppEnv = Literal["development", "test", "production"]
_ENVIRONMENTS: tuple[AppEnv, ...] = ("development", "test", "production")
_TRUE = {"1", "true", "yes", "on"}

# The OWASP Password Storage Cheat Sheet minimum for argon2id (19 MiB, 2 iterations, 1 lane).
ARGON2_MIN_TIME_COST = 2
ARGON2_MIN_MEMORY_KIB = 19_456


class ConfigError(Exception):
    """A setting is missing or invalid. Raised before the app serves anything."""


def _read_int(env: Mapping[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class Weaknesses:
    """Deliberate weaknesses, one per control of the threat model, all off by default.

    They exist so the test suite can prove each control by running the same tests with the control removed and
    watching them fail. They are only accepted when ``APP_ENV=test``.
    """

    weak_password_hash: bool = False
    sql_concatenation: bool = False
    raw_note_output: bool = False
    skip_ownership_check: bool = False
    weak_session_cookie: bool = False
    skip_csrf: bool = False
    skip_security_headers: bool = False

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Weaknesses:
        """Read ``UNSAFE_<NAME>`` variables; anything but 1, true, yes or on means off."""
        return cls(**{f.name: env.get(f"UNSAFE_{f.name.upper()}", "").lower() in _TRUE for f in fields(cls)})

    def enabled(self) -> tuple[str, ...]:
        """The names of the weaknesses that are switched on."""
        return tuple(f.name for f in fields(self) if getattr(self, f.name))


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection settings of the application's limited PostgreSQL role."""

    host: str
    port: int
    name: str
    user: str
    password: str = field(repr=False)
    pool_min: int = 1
    pool_max: int = 8
    connect_timeout_seconds: int = 5

    def conninfo(self) -> str:
        """A libpq connection string. Contains the password; never log it."""
        return (
            f"host={self.host} port={self.port} dbname={self.name} user={self.user} "
            f"password={self.password} connect_timeout={self.connect_timeout_seconds}"
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the application reads from its environment."""

    app_env: AppEnv
    host: str
    port: int
    log_level: str
    trusted_proxy_count: int
    database: DatabaseSettings
    argon2_time_cost: int
    argon2_memory_kib: int
    argon2_parallelism: int
    session: SessionPolicy
    login_max_failures: int
    login_window_seconds: int
    weaknesses: Weaknesses

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Settings:
        """Build and validate settings; raise ``ConfigError`` naming the first problem."""
        app_env = env.get("APP_ENV", "production")
        if app_env not in _ENVIRONMENTS:
            raise ConfigError(f"APP_ENV must be one of {', '.join(_ENVIRONMENTS)}, got {app_env!r}")
        password = env.get("NOTES_DB_PASSWORD", "")
        if not password:
            raise ConfigError("NOTES_DB_PASSWORD is required (set it in .env or the environment)")
        settings = cls(
            app_env=app_env,
            host=env.get("APP_HOST", "127.0.0.1"),
            port=_read_int(env, "APP_PORT", 8047),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            trusted_proxy_count=_read_int(env, "TRUSTED_PROXY_COUNT", 0, minimum=0),
            database=DatabaseSettings(
                host=env.get("NOTES_DB_HOST", "localhost"),
                port=_read_int(env, "NOTES_DB_PORT", 5471),
                name=env.get("NOTES_DB_NAME", "notes"),
                user=env.get("NOTES_DB_USER", "notes_app"),
                password=password,
                pool_min=_read_int(env, "NOTES_DB_POOL_MIN", 1),
                pool_max=_read_int(env, "NOTES_DB_POOL_MAX", 8),
            ),
            argon2_time_cost=_read_int(env, "ARGON2_TIME_COST", ARGON2_MIN_TIME_COST),
            argon2_memory_kib=_read_int(env, "ARGON2_MEMORY_KIB", ARGON2_MIN_MEMORY_KIB),
            argon2_parallelism=_read_int(env, "ARGON2_PARALLELISM", 1),
            session=SessionPolicy(
                idle_seconds=_read_int(env, "SESSION_IDLE_SECONDS", 1800),
                absolute_seconds=_read_int(env, "SESSION_ABSOLUTE_SECONDS", 28800),
                anonymous_seconds=_read_int(env, "ANONYMOUS_SESSION_SECONDS", 900),
            ),
            login_max_failures=_read_int(env, "LOGIN_MAX_FAILURES", 5),
            login_window_seconds=_read_int(env, "LOGIN_WINDOW_SECONDS", 900),
            weaknesses=Weaknesses.from_environment(env),
        )
        settings._validate()
        return settings

    def _validate(self) -> None:
        enabled = self.weaknesses.enabled()
        if enabled and self.app_env != "test":
            raise ConfigError(f"deliberate weaknesses ({', '.join(enabled)}) are only accepted when APP_ENV=test")
        weak_argon2 = self.argon2_time_cost < ARGON2_MIN_TIME_COST or self.argon2_memory_kib < ARGON2_MIN_MEMORY_KIB
        if weak_argon2 and self.app_env != "test":
            raise ConfigError(
                f"argon2 parameters are below the OWASP minimum ({ARGON2_MIN_TIME_COST} iterations, "
                f"{ARGON2_MIN_MEMORY_KIB} KiB)"
            )
        if self.database.pool_min > self.database.pool_max:
            raise ConfigError("NOTES_DB_POOL_MIN must not exceed NOTES_DB_POOL_MAX")
        if self.session.anonymous_seconds > self.session.absolute_seconds:
            raise ConfigError("ANONYMOUS_SESSION_SECONDS must not exceed SESSION_ABSOLUTE_SECONDS")
