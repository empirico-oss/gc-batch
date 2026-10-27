"""Utility functions for gc-batch.

This module provides helper functions for working with Google Cloud Batch jobs,
including authentication utilities, time formatting, and job state checking.
"""

import configparser
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth import default
from google.auth.exceptions import DefaultCredentialsError
from google.cloud.batch_v1.types import Job as GCSBatchJob
from google.cloud.batch_v1.types import JobStatus


def get_gc_batch_version() -> str:
    """Get the version of the gc-batch package.

    Returns:
        The version string of the gc-batch package.
    """
    from gc_batch._version import version as gc_batch_version

    return gc_batch_version


def get_current_account() -> str | None:
    """Get the current authenticated Google Cloud account.

    Tries to get the account from gcloud config first, then falls back
    to google.auth.default() if gcloud is not available.

    Returns:
        The email address of the current authenticated account, or None if
        authentication fails.

    Example:
        ```python
        account = get_current_account()
        if account:
            print(f"Logged in as: {account}")
        else:
            print("Not authenticated")
        ```
    """
    try:
        # First try to get from gcloud config (this matches the command line behavior)
        result = subprocess.run(
            ["gcloud", "config", "get-value", "account"],
            capture_output=True,
            text=True,
            check=True,
        )
        account = result.stdout.strip()
        if account and account != "default":
            return account
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"DEBUG: gcloud config failed: {e}")

    # Fallback to google.auth.default() if gcloud is not available
    try:
        credentials, project = default()
        auth_account = credentials.service_account_email or credentials.signer_email
        print(f"DEBUG: google.auth.default() returned: '{auth_account}'")
        return auth_account
    except DefaultCredentialsError as e:
        print(f"DEBUG: google.auth.default() failed: {e}")
        return None


_METADATA_ZONE_URL = "http://metadata.google.internal/computeMetadata/v1/instance/zone"


def get_current_region() -> str | None:
    """Get the GCP region of the machine gc-batch is running on.

    Asks the GCE metadata server for the current VM's zone (e.g.
    ``projects/123/zones/us-east1-b``) and strips the zone suffix. In the All of
    Us Researcher Workbench the notebook VM runs in the workspace's region, so
    this is the region jobs must be placed in. Falls back to the
    ``compute/region`` property of the active ``gcloud`` configuration when the
    metadata server is unreachable (i.e. when not running on GCE).

    Every command calls this when ``--location`` is not given, so it avoids
    running ``gcloud`` (which takes most of a second) and reads its config files.

    Returns:
        The region name (e.g. "us-east1"), or None if it could not be determined.
    """
    request = urllib.request.Request(_METADATA_ZONE_URL, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            zone = response.read().decode().strip().rsplit("/", 1)[-1]
        if zone.count("-") >= 2:
            return zone.rsplit("-", 1)[0]
    except (urllib.error.URLError, OSError):
        pass

    return _gcloud_compute_region()


def _gcloud_compute_region() -> str | None:
    """Read ``compute/region`` the way ``gcloud config get-value`` resolves it.

    Honors ``$CLOUDSDK_COMPUTE_REGION``, ``$CLOUDSDK_CONFIG`` and
    ``$CLOUDSDK_ACTIVE_CONFIG_NAME``, then the active named configuration file.

    Returns:
        The configured region, or None if it is unset or unreadable.
    """
    region = os.getenv("CLOUDSDK_COMPUTE_REGION")
    if region:
        return region

    config_dir = Path(os.getenv("CLOUDSDK_CONFIG") or Path.home() / ".config" / "gcloud")
    try:
        active = os.getenv("CLOUDSDK_ACTIVE_CONFIG_NAME") or (
            (config_dir / "active_config").read_text().strip()
        )
    except OSError:
        active = "default"

    parser = configparser.ConfigParser()
    try:
        parser.read(config_dir / "configurations" / f"config_{active or 'default'}")
    except configparser.Error:
        return None
    return parser.get("compute", "region", fallback=None) or None


def resolve_created_by_label(owner_email_env_vars: list[str]) -> str:
    """Resolve the "created-by" label value from the current environment.

    The first environment variable in ``owner_email_env_vars`` that is set
    provides the value. Email-shaped values are reduced to their local part and
    normalized for GCP label rules (e.g. "jane.doe@example.com" becomes
    "jane-doe").

    Args:
        owner_email_env_vars: Environment variable names to check, in order.
            Typically ``settings.owner_email_env_vars``.

    Returns:
        The label value, or "unknown" when none of the variables are set.

    Example:
        ```python
        from gc_batch import GCBatchSettings
        from gc_batch.utils import resolve_created_by_label

        settings = GCBatchSettings()
        print(resolve_created_by_label(settings.owner_email_env_vars))
        ```
    """
    for env_var in owner_email_env_vars:
        value = os.getenv(env_var)
        if value:
            return value.split("@")[0].replace(".", "-")

    return "unknown"


def is_job_finished(job: GCSBatchJob) -> bool:
    """Check if a job has reached a terminal state.

    Terminal states include SUCCEEDED, FAILED, CANCELLED, DELETION_IN_PROGRESS,
    and CANCELLATION_IN_PROGRESS.

    Args:
        job: The GCSBatchJob to check.

    Returns:
        True if the job is in a terminal state, False otherwise.

    Example:
        ```python
        job = client.get_job("my-job")
        if is_job_finished(job):
            print(f"Job finished with state: {job.status.state.name}")
        ```
    """
    return job.status.state in [
        JobStatus.State.SUCCEEDED,
        JobStatus.State.FAILED,
        JobStatus.State.CANCELLED,
        JobStatus.State.DELETION_IN_PROGRESS,
        JobStatus.State.CANCELLATION_IN_PROGRESS,
    ]


def format_time_for_filter(timestamp: datetime | str | None) -> str | None:
    """
    Convert a timestamp to RFC3339 format for Cloud Logging filters.

    Args:
        timestamp: A timestamp object (e.g., from job.create_time or job.update_time)

    Returns:
        str: RFC3339 formatted timestamp string, or None if timestamp is None
    """
    # Convert to RFC3339 format if it's a timestamp object
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()

    # If it's already a string, return as-is
    if isinstance(timestamp, str):
        return timestamp

    return None


def get_start_and_end_time(job: GCSBatchJob) -> tuple[datetime | None, datetime | None]:
    """
    Get the start and end time for a job.
    If the job is finished, the end time is the update time.
    If the job is not finished, the end time is None.
    The start time is the create time.
    Returns:
        Tuple[str, Optional[str]]: The start and end time for the job
            The start time is the create time.
            The end time is the update time if the job is finished, otherwise None.
    """
    if is_job_finished(job):
        end_time = job.update_time
    else:
        end_time = None
    start_time = job.create_time
    return start_time, end_time


def get_formatted_start_and_end_time(
    job: GCSBatchJob, include_end_time_when_not_finished: bool = False
) -> tuple[str | None, str | None]:
    """
    Get the formatted start and end time for a job.

    Args:
        job: The GCSBatchJob object to get the start and end time for
        include_end_time_when_not_finished: Whether to include the end time when the job is not finished

    Returns:
        Tuple[Optional[str], Optional[str]]: The formatted start and end time for the job
            - RFC3339 formatted timestamp string
            - RFC3339 formatted timestamp string, or None if timestamp is None
            - If include_end_time_when_not_finished is True and the end time is None, the end time will be the current time.
            - If the current time is within 20 minutes of the start time, the end time will start time + 1 hour.
    """
    start_time, end_time = get_start_and_end_time(job)
    formatted_start_time = format_time_for_filter(start_time)
    formatted_end_time = format_time_for_filter(end_time)
    if start_time and include_end_time_when_not_finished and end_time is None:
        # Use UTC timezone-aware datetime to match Google Cloud Batch timestamps
        # Google Cloud Batch returns timezone-aware datetimes, so we need to match that
        current_time = datetime.now(timezone.utc)
        # Ensure start_time is timezone-aware for comparison
        # If it's naive (shouldn't happen with Google Cloud Batch, but handle it defensively),
        # assume it's UTC and make it timezone-aware
        if isinstance(start_time, datetime) and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if current_time - start_time < timedelta(minutes=20):
            formatted_end_time = (start_time + timedelta(hours=1)).isoformat()
        else:
            formatted_end_time = format_time_for_filter(current_time)
    return formatted_start_time, formatted_end_time
