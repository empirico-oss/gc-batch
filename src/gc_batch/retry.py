"""Retry policy for Google Cloud Batch API rate-limit (429) errors.

Google Cloud Batch enforces per-region read quotas ("Read requests per minute
per region"). Anything that polls job status on a short interval — for example
``remotely``'s batch backend calling :meth:`GCBatchClient.list_jobs` and
:meth:`GCBatchClient.get_job` — can exhaust the quota and receive
``ResourceExhausted`` (HTTP 429) errors. The google-api-core client already
retries internally, but its budget is short and the quota resets only once a
minute, so a burst of polls still surfaces the error to the caller.

The decorator here adds a slow, jittered exponential backoff on top, tuned for
a quota that resets every minute: waits start at a few seconds, grow to at most
a minute, and give up after a bounded total timeout. When retries are
exhausted, the original ``ResourceExhausted`` exception is re-raised (tenacity
``reraise=True``), so callers see the same exception they would have seen
without the retry.

All knobs are overridable with environment variables so callers can tune the
backoff without code changes:

    GC_BATCH_RETRY_INITIAL_DELAY_SECONDS: First backoff delay (default 2).
    GC_BATCH_RETRY_MAX_DELAY_SECONDS: Largest backoff delay (default 60).
    GC_BATCH_RETRY_TIMEOUT_SECONDS: Total wall-clock time to keep retrying
        before giving up (default 300).
    GC_BATCH_RETRY_MAX_ATTEMPTS: Hard cap on attempts, regardless of the
        timeout (default 12).
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

from google.api_core import exceptions
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)
from tenacity import nap as tenacity_nap

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

#: 429-equivalent exceptions: the Batch API is called over gRPC, which raises
#: ResourceExhausted; plain-HTTP transports raise TooManyRequests.
RATE_LIMIT_EXCEPTIONS = (exceptions.ResourceExhausted, exceptions.TooManyRequests)

INITIAL_DELAY_ENV = "GC_BATCH_RETRY_INITIAL_DELAY_SECONDS"
MAX_DELAY_ENV = "GC_BATCH_RETRY_MAX_DELAY_SECONDS"
TIMEOUT_ENV = "GC_BATCH_RETRY_TIMEOUT_SECONDS"
MAX_ATTEMPTS_ENV = "GC_BATCH_RETRY_MAX_ATTEMPTS"

DEFAULT_INITIAL_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_TIMEOUT = 300.0
DEFAULT_MAX_ATTEMPTS = 12


def _env_float(name: str, default: float) -> float:
    """Read a float from an environment variable, falling back to a default.

    Invalid values log a warning and use the default rather than crashing a
    job that is already struggling with rate limits.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid value %r for %s; using default %s instead.", raw, name, default)
        return default


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to a default."""
    value = _env_float(name, float(default))
    return max(1, int(value))


def _wait_exponential_jitter(initial: float, max_delay: float):
    """Build a jittered exponential wait, across tenacity API generations.

    tenacity 9 renamed ``wait_exponential_jitter``'s ``initial`` parameter to
    ``multiplier`` (and warns on ``initial``); tenacity 8 only has ``initial``.
    """
    try:
        return wait_exponential_jitter(multiplier=initial, max=max_delay)  # tenacity >= 9
    except TypeError:  # tenacity < 9
        return wait_exponential_jitter(initial=initial, max=max_delay)


def _build_retrying() -> Retrying:
    """Build a Retrying with the current environment-tuned parameters.

    Parameters are read on every call so that environment changes (and test
    monkeypatching) take effect without re-importing the module.
    """
    return Retrying(
        # Look up nap.sleep at build time so tests can patch the sleep.
        sleep=tenacity_nap.sleep,
        retry=retry_if_exception_type(RATE_LIMIT_EXCEPTIONS),
        wait=_wait_exponential_jitter(
            initial=_env_float(INITIAL_DELAY_ENV, DEFAULT_INITIAL_DELAY),
            max_delay=_env_float(MAX_DELAY_ENV, DEFAULT_MAX_DELAY),
        ),
        # Give up after the timeout OR the attempt cap, whichever comes first.
        # The attempt cap also bounds retry loops when time is faked in tests.
        stop=stop_after_delay(_env_float(TIMEOUT_ENV, DEFAULT_TIMEOUT))
        | stop_after_attempt(_env_int(MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def retry_on_rate_limit(func: F) -> F:
    """Retry ``func`` with exponential backoff whenever the API returns 429.

    Only rate-limit errors are retried; every other exception (permission
    errors, invalid filters, network failures, ...) propagates immediately.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _build_retrying()(func, *args, **kwargs)

    return wrapper  # type: ignore[return-value]
