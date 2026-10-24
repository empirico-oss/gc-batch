"""Tests for the retry_on_rate_limit decorator itself.

The client-level behavior (``get_job``/``list_jobs`` retrying on 429) is
covered in ``test_client.py``; these tests exercise the decorator directly:
bare vs. parameterized usage, argument precedence over the ``GC_BATCH_RETRY_*``
environment variables, and decoration-time validation.
"""

import pytest
from google.api_core.exceptions import PermissionDenied, ResourceExhausted

from gc_batch.retry import retry_on_rate_limit


class TestRetryDecorator:
    @pytest.fixture(autouse=True)
    def _no_sleeping(self, monkeypatch):
        """Make retry backoff instant and observable."""
        self.sleeps: list[float] = []
        monkeypatch.setattr("tenacity.nap.sleep", lambda seconds: self.sleeps.append(seconds))

    @staticmethod
    def _flaky(times_to_fail: int):
        """Return a function that fails with 429 N times, then succeeds."""
        calls = []

        def func():
            calls.append(len(calls) + 1)
            if len(calls) <= times_to_fail:
                raise ResourceExhausted("429 quota exceeded")
            return "ok"

        func.call_count = lambda: len(calls)
        return func

    @staticmethod
    def _always_fails():
        """Return a function that always fails with 429."""
        calls = []

        def func():
            calls.append(len(calls) + 1)
            raise ResourceExhausted("429 quota exceeded")

        func.call_count = lambda: len(calls)
        return func

    def test_bare_decorator_retries_and_succeeds(self):
        func = self._flaky(times_to_fail=2)

        result = retry_on_rate_limit(func)()

        assert result == "ok"
        assert func.call_count() == 3
        assert len(self.sleeps) == 2

    def test_parameterized_decorator_retries_and_succeeds(self):
        func = self._flaky(times_to_fail=2)

        result = retry_on_rate_limit(timeout=400, initial_delay=3)(func)()

        assert result == "ok"
        assert func.call_count() == 3

    def test_empty_parentheses_behave_like_bare(self):
        func = self._always_fails()

        with pytest.raises(ResourceExhausted):
            retry_on_rate_limit()(func)()

        # The default attempt cap is 12: one initial call plus 11 retries.
        assert func.call_count() == 12

    def test_decorator_arguments_override_environment(self, monkeypatch):
        """An explicit argument is more specific than the environment."""
        monkeypatch.setenv("GC_BATCH_RETRY_MAX_ATTEMPTS", "5")
        func = self._always_fails()

        with pytest.raises(ResourceExhausted):
            retry_on_rate_limit(max_attempts=3)(func)()

        assert func.call_count() == 3

    def test_environment_applies_without_decorator_arguments(self, monkeypatch):
        monkeypatch.setenv("GC_BATCH_RETRY_MAX_ATTEMPTS", "2")
        func = self._always_fails()

        with pytest.raises(ResourceExhausted):
            retry_on_rate_limit(func)()

        assert func.call_count() == 2

    def test_invalid_arguments_raise_at_decoration_time(self):
        with pytest.raises(ValueError, match="timeout"):
            retry_on_rate_limit(timeout=0)
        with pytest.raises(ValueError, match="initial_delay"):
            retry_on_rate_limit(initial_delay=-1)
        with pytest.raises(ValueError, match="max_delay"):
            retry_on_rate_limit(max_delay=0)
        with pytest.raises(ValueError, match="max_attempts"):
            retry_on_rate_limit(max_attempts=0)

    def test_non_rate_limit_errors_are_not_retried(self):
        def func():
            raise PermissionDenied("403")

        func.call_count = lambda: 1

        with pytest.raises(PermissionDenied):
            retry_on_rate_limit(timeout=400)(func)()

        assert self.sleeps == []

    def test_initial_delay_sets_the_first_backoff(self):
        """The first wait is initial_delay plus at most one second of jitter."""
        func = self._flaky(times_to_fail=1)

        retry_on_rate_limit(initial_delay=3)(func)()

        assert 3 <= self.sleeps[0] <= 4

    def test_max_delay_caps_the_backoff(self):
        """Waits never exceed max_delay plus jitter."""
        func = self._flaky(times_to_fail=5)

        retry_on_rate_limit(initial_delay=2, max_delay=5)(func)()

        assert all(delay <= 6 for delay in self.sleeps)

    def test_original_exception_is_reraised_not_wrapped(self):
        func = self._always_fails()

        with pytest.raises(ResourceExhausted):
            retry_on_rate_limit(max_attempts=2)(func)()

    def test_decorator_preserves_function_metadata(self):
        def poll_batch_status():
            return "ok"

        poll_batch_status.call_count = lambda: 0

        wrapped = retry_on_rate_limit(timeout=400)(poll_batch_status)

        assert wrapped.__name__ == "poll_batch_status"
        assert wrapped.__doc__ == poll_batch_status.__doc__
