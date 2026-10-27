"""Sign-up and sign-in."""

from __future__ import annotations

from notes_app.application.ports import AuditLog, Clock, LoginThrottle, PasswordHasher, UserRepository
from notes_app.domain.errors import AuthenticationFailedError, InvalidInputError, LoginThrottledError
from notes_app.domain.models import AuditAction, AuditEvent, User
from notes_app.domain.validation import validate_password, validate_username


class AccountService:
    """Registers users and checks credentials. Passwords are hashed here and appear nowhere else."""

    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        throttle: LoginThrottle,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._throttle = throttle
        self._audit = audit
        self._clock = clock

    def register(self, username: str, password: str, ip: str) -> User:
        """Create a user with a salted hash. Raises ``InvalidInputError`` or ``UsernameTakenError``."""
        canonical = validate_username(username)
        user = self._users.add(canonical, self._hasher.hash(validate_password(password)))
        self._audit.record(AuditEvent(AuditAction.SIGNUP, "success", user.id, ip))
        return user

    def authenticate(self, username: str, password: str, ip: str) -> User:
        """Return the user for a correct username and password.

        Raises ``LoginThrottledError`` when the client has failed too often, and ``AuthenticationFailedError``
        for any wrong credential. The two failure causes (unknown user, wrong password) are indistinguishable in
        the response and in the time taken.
        """
        key = f"{ip}|{username.strip().lower()}"
        now = self._clock.now()
        try:
            self._throttle.check(key, now)
        except LoginThrottledError:
            self._audit.record(AuditEvent(AuditAction.LOGIN_THROTTLED, "refused", None, ip))
            raise
        user = self._find(username)
        if user is None or not self._hasher.verify(password, user.password_hash):
            if user is None:
                self._hasher.spend_equal_effort(password)
            self._throttle.record_failure(key, now)
            self._audit.record(AuditEvent(AuditAction.LOGIN_FAILURE, "failure", user.id if user else None, ip))
            raise AuthenticationFailedError("invalid username or password")
        self._throttle.reset(key)
        if self._hasher.needs_rehash(user.password_hash):
            self._users.update_password_hash(user.id, self._hasher.hash(password))
        self._audit.record(AuditEvent(AuditAction.LOGIN_SUCCESS, "success", user.id, ip))
        return user

    def get_user(self, user_id: int) -> User | None:
        """The user with this id, for the page header of a signed-in session."""
        return self._users.by_id(user_id)

    def _find(self, username: str) -> User | None:
        try:
            return self._users.by_username(validate_username(username))
        except InvalidInputError:
            return None
