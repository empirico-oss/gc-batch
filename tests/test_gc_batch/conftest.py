"""Shared fixtures for the gc-batch test suite."""

import pytest


@pytest.fixture
def retry_sleeps(monkeypatch) -> list[float]:
    """Patch tenacity's sleep so retry backoff is instant and observable.

    Returns the list of backoff delays (in seconds) that would have been
    slept, so tests can assert on the retry cadence without waiting.
    """
    sleeps: list[float] = []
    monkeypatch.setattr("tenacity.nap.sleep", lambda seconds: sleeps.append(seconds))
    return sleeps
