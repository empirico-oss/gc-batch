"""Retry policy for Google Cloud API rate-limit (429) errors.

Google Cloud enforces per-region, per-minute quotas on its services: the
Batch API limits "Read requests per minute per region", Cloud Logging limits
entries read per minute, and GCS limits requests per bucket. Anything that
polls on a short interval — for example ``remotely``'s batch backend calling
:meth:`GCBatchClient.list_jobs` and :meth:`GCBatchClient.get_job` — can
exhaust a quota and receive ``ResourceExhausted`` (HTTP 429) errors. The
google-api-core client already retries internally, but its budget is short
and quotas reset only once a minute, so a burst of requests still surfaces
the error to the caller.

The decorator here adds a slow, jittered exponential backoff on top, tuned
for quotas that reset every minute: waits start at a few seconds, grow to at
most a minute, and give up after a bounded total timeout. It is applied to
gc-batch's read requests — Batch API ``jobs.get``/``jobs.list``, Cloud
Logging ``entries.list``, and GCS log-object listing and downloads. When
retries are exhausted, the original ``ResourceExhausted`` exception is
re-raised (tenacity ``reraise=True``), so callers see the same exception
they would have seen without the retry.

Every knob can be set three ways, in decreasing precedence:

1. Decorator arguments::

       @retry_on_rate_limit(timeout=400, initial_delay=3)
       def poll(...): ...

2. Environment variables (read at call time, so a deployment can tune the
   backoff of code it does not own):

       GC_BATCH_RETRY_INITIAL_DELAY_SECONDS: First backoff delay (default 2).
       GC_BATCH_RETRY_MAX_DELAY_SECONDS: Largest backoff delay (default 60).
       GC_BATCH_RETRY_TIMEOUT_SECONDS: Total wall-clock time to keep retrying
           before giving up (default 300).
       GC_BATCH_RETRY_MAX_ATTEMPTS: Hard cap on attempts, regardless of the
           timeout (default 12).

3. Built-in defaults, shown above.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar, overload

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

#: 429-equivalent exceptions: Google Cloud clients called over gRPC raise
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


def _check_positive(name: str, value: float) -> None:
    """Reject non-positive decorator overrides with an actionable error."""
    if value <= 0:
        raise ValueError(f"retry_on_rate_limit: {name} must be positive, got {value!r}")


def _build_retrying(
    initial_delay: float | None = None,
    max_delay: float | None = None,
    timeout: float | None = None,
    max_attempts: int | None = None,
) -> Retrying:
    """Build a Retrying from decorator overrides, environment, and defaults.

    Decorator overrides win over environment variables, which win over the
    built-in defaults. Parameters are resolved on every call so that
    environment changes (and test monkeypatching) take effect without
    re-importing the module.
    """
    initial = (
        _env_float(INITIAL_DELAY_ENV, DEFAULT_INITIAL_DELAY)
        if initial_delay is None
        else initial_delay
    )
    delay_cap = _env_float(MAX_DELAY_ENV, DEFAULT_MAX_DELAY) if max_delay is None else max_delay
    total_timeout = _env_float(TIMEOUT_ENV, DEFAULT_TIMEOUT) if timeout is None else timeout
    attempts = (
        _env_int(MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS) if max_attempts is None else max_attempts
    )

    return Retrying(
        # Look up nap.sleep at build time so tests can patch the sleep.
        sleep=tenacity_nap.sleep,
        retry=retry_if_exception_type(RATE_LIMIT_EXCEPTIONS),
        wait=_wait_exponential_jitter(initial=initial, max_delay=delay_cap),
        # Give up after the timeout OR the attempt cap, whichever comes first.
        # The attempt cap also bounds retry loops when time is faked in tests.
        stop=stop_after_delay(total_timeout) | stop_after_attempt(attempts),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


@overload
def retry_on_rate_limit(func: F) -> F: ...


@overload
def retry_on_rate_limit(
    *,
    initial_delay: float | None = None,
    max_delay: float | None = None,
    timeout: float | None = None,
    max_attempts: int | None = None,
) -> Callable[[F], F]: ...


def retry_on_rate_limit(
    func: F | None = None,
    *,
    initial_delay: float | None = None,
    max_delay: float | None = None,
    timeout: float | None = None,
    max_attempts: int | None = None,
) -> F | Callable[[F], F]:
    """Retry ``func`` with exponential backoff whenever the API returns 429.

    Usable bare or with keyword arguments that override the
    ``GC_BATCH_RETRY_*`` environment variables and the built-in defaults:

        @retry_on_rate_limit
        def poll_a(): ...

        @retry_on_rate_limit(timeout=400, initial_delay=3, max_delay=90)
        def poll_b(): ...

    Args:
        func: The function to wrap (when the decorator is used bare).
        initial_delay: First backoff delay, in seconds. Defaults to
            ``$GC_BATCH_RETRY_INITIAL_DELAY_SECONDS`` or 2.
        max_delay: Largest backoff delay, in seconds. Defaults to
            ``$GC_BATCH_RETRY_MAX_DELAY_SECONDS`` or 60.
        timeout: Total wall-clock seconds to keep retrying before giving up.
            Defaults to ``$GC_BATCH_RETRY_TIMEOUT_SECONDS`` or 300.
        max_attempts: Hard cap on attempts regardless of the timeout.
            Defaults to ``$GC_BATCH_RETRY_MAX_ATTEMPTS`` or 12.

    Only rate-limit errors are retried; every other exception (permission
    errors, invalid filters, network failures, ...) propagates immediately.
    Decorator arguments that are not positive raise ``ValueError`` at
    decoration time.

    Returns:
        The wrapped function. When retries are exhausted, the wrapped call
        re-raises the original rate-limit exception.
    """
    if initial_delay is not None:
        _check_positive("initial_delay", initial_delay)
    if max_delay is not None:
        _check_positive("max_delay", max_delay)
    if timeout is not None:
        _check_positive("timeout", timeout)
    if max_attempts is not None and max_attempts < 1:
        raise ValueError(f"retry_on_rate_limit: max_attempts must be >= 1, got {max_attempts!r}")

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _build_retrying(
                initial_delay=initial_delay,
                max_delay=max_delay,
                timeout=timeout,
                max_attempts=max_attempts,
            )(fn, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    if func is None:
        # Used with arguments: @retry_on_rate_limit(timeout=400, ...)
        return decorator
    # Used bare: @retry_on_rate_limit
    return decorator(func)
