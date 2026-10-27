from datetime import timedelta

from notes_app.domain.throttle import retry_after_seconds
from tests.fakes import START

WINDOW = timedelta(minutes=10)


def wait(failures, now=START, max_failures=3):
    return retry_after_seconds(failures, now=now, max_failures=max_failures, window=WINDOW)


def test_failures_below_the_limit_do_not_throttle():
    assert wait([START, START]) is None
    assert wait([]) is None


def test_the_limit_throttles_until_the_blocking_failure_ages_out():
    failures = [START, START + timedelta(seconds=1), START + timedelta(seconds=2)]
    assert wait(failures, now=START + timedelta(seconds=10)) == 591


def test_failures_outside_the_window_are_ignored():
    old = [START - timedelta(minutes=11)] * 5
    assert wait(old) is None
    assert wait([*old, START]) is None


def test_the_wait_is_never_less_than_one_second():
    failures = [START - timedelta(minutes=10) + timedelta(milliseconds=1)] * 3
    assert wait(failures) == 1


def test_with_more_failures_than_the_limit_the_wait_follows_the_newest_blocking_set():
    failures = [START + timedelta(seconds=n) for n in range(5)]
    assert wait(failures, now=START + timedelta(seconds=5)) == 598
