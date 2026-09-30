"""Logging utilities for Google Cloud Batch jobs.

This module provides functionality for retrieving, filtering, and displaying
logs from Google Cloud Batch jobs using Cloud Logging.

Classes:
    BatchLogging: Main class for batch job log operations.
"""

import logging
import os
from urllib.parse import quote

from google.cloud import batch_v1
from google.cloud import logging as cloud_logging
from google.cloud.batch_v1.types import Job as GCSBatchJob

from gc_batch.google_utils import GoogleUtils
from gc_batch.logger import Logger, get_logger
from gc_batch.models.batch_config import BatchClientConfig
from gc_batch.utils import get_formatted_start_and_end_time


def format_log_entry(log: dict) -> str:
    """Render a log entry dict as a single console/file line.

    Args:
        log: A log entry in the shape produced by ``BatchLogging._query_cloud_logs``
            and ``GCSLogReader.read_logs_for_job``.

    Returns:
        The formatted ``[timestamp] SEVERITY: message`` line.
    """
    timestamp = log.get("timestamp", "Unknown time")
    severity = log.get("severity", "INFO")
    message = log.get("textPayload", "")
    return f"[{timestamp}] {severity}: {message}"


class BatchLogging:
    """Utilities for retrieving and managing Google Cloud Batch job logs.

    This class provides methods to:
    - Print job logs to the console
    - Download logs to local files
    - Generate Cloud Logging filter strings
    - Generate Cloud Console URLs for viewing logs
    - Query Cloud Logging for job-specific entries

    Attributes:
        config: The BatchClientConfig with project settings.
        cloud_logging_client: Google Cloud Logging client instance.

    Example:
        ```python
        from gc_batch import BatchClientConfig
        from gc_batch.batch_logging import BatchLogging

        config = BatchClientConfig(project_id="my-project", location="us-central1")
        logging = BatchLogging(config)

        # Get a job and print its logs
        job = client.get_job("my-job-name")
        logging.print_logs_for_job(job)

        # Download logs to a directory
        logging.download_logs_for_job(job, "./logs")

        # Get a URL to view logs in Cloud Console
        url = logging.get_cloud_logging_url(job)
        print(f"View logs at: {url}")
        ```
    """

    def __init__(
        self,
        config: BatchClientConfig,
        logger: Logger | None = None,
        log_level: int = logging.INFO,
    ):
        """Initialize the BatchLogging instance.

        Args:
            config: Configuration with project_id and location settings.
        """
        self.config = config
        self.logging = logger or get_logger(name="BatchLogging", level=log_level)
        self.cloud_logging_client = cloud_logging.Client(project=self.config.project_id)

    def create_log_policy(self, logs_path: str | None = None) -> batch_v1.LogsPolicy:
        """Create the logs policy that tells Batch API where to write logs.

        Args:
            logs_path: Optional absolute path on the VM (typically a mounted GCS
                volume) where logs should be written. When provided, the Batch job
                writes logs to this path (``destination=PATH``) instead of Cloud
                Logging. Batch only supports a single destination, so providing a
                path disables Cloud Logging for the job.

        Returns:
            A configured ``LogsPolicy``. Uses ``PATH`` when ``logs_path`` is set,
            otherwise ``CLOUD_LOGGING``.
        """
        if logs_path:
            return batch_v1.LogsPolicy(
                destination=batch_v1.LogsPolicy.Destination.PATH,
                logs_path=logs_path,
            )
        return batch_v1.LogsPolicy(destination=batch_v1.LogsPolicy.Destination.CLOUD_LOGGING)

    def download_logs_for_job(
        self, job: GCSBatchJob, download_dir: str, severity: str = "DEFAULT"
    ) -> int:
        """Download a job's Cloud Logging entries into a single local file.

        Args:
            job: The GCSBatchJob object to download logs for.
            download_dir: Directory to save the logs. Created if it does not exist.
            severity: Minimum severity level for logs.

        Returns:
            The number of entries written. Zero means the query succeeded but
            nothing matched, and no file is written.

        Raises:
            google.api_core.exceptions.GoogleAPIError: If the Cloud Logging query
                fails (for example, the caller cannot read logs in this project).
            OSError: If the log file cannot be written.
        """
        try:
            filter_str = self.get_filter_string_for_job(job, severity)
            logs = self._query_cloud_logs(filter_str)
        except Exception as e:
            # Logged at debug only: the exception propagates to the caller, which
            # reports it once. _query_cloud_logs has already logged the filter,
            # which is the part this message would not repeat.
            self.logging.debug(f"Error retrieving logs for job {job.name}: {e}")
            raise

        if not logs:
            self.logging.warning(f"No log entries matched the query for job {job.name}")
            print(f"No log entries matched the query for job {job.name}")
            return 0

        # Sort logs chronologically by timestamp
        logs = self._sort_logs_chronologically(logs)

        os.makedirs(download_dir, exist_ok=True)
        # Extract just the job ID from the full job name (e.g., "my-job-1234567890")
        job_name = GoogleUtils.get_job_name(job)
        log_file = os.path.join(download_dir, f"{job_name}.log")

        with open(log_file, "w") as f:
            for log in logs:
                f.write(f"{format_log_entry(log)}\n")

        self.logging.debug(f"Downloaded {len(logs)} log entries to {log_file}")
        return len(logs)

    def print_logs_for_job(
        self,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
    ) -> int:
        """Print a job's Cloud Logging entries to the console.

        Args:
            job: The GCSBatchJob object to print logs for.
            severity: Minimum severity level for logs.

        Returns:
            The number of entries printed. Zero means the query succeeded but
            nothing matched.

        Raises:
            google.api_core.exceptions.GoogleAPIError: If the Cloud Logging query
                fails (for example, the caller cannot read logs in this project).
        """
        try:
            filter_str = self.get_filter_string_for_job(job, severity)
            logs = self._query_cloud_logs(filter_str)
        except Exception as e:
            # Logged at debug only: the exception propagates to the caller, which
            # reports it once. _query_cloud_logs has already logged the filter,
            # which is the part this message would not repeat.
            self.logging.debug(f"Error retrieving logs for job {job.name}: {e}")
            raise

        if not logs:
            self.logging.warning(f"No log entries matched the query for job {job.name}")
            print(f"No log entries matched the query for job {job.name}")
            return 0

        # Sort logs chronologically by timestamp
        logs = self._sort_logs_chronologically(logs)

        # Print all logs in chronological order
        print(f"\n{'=' * 80}")
        print(f"LOGS FOR JOB: {job.name} (Chronological Order)")
        print(f"{'=' * 80}")
        for log in logs:
            print(format_log_entry(log))
        return len(logs)

    @classmethod
    def get_time_range_filters(cls, job: GCSBatchJob) -> list[str]:
        """Get the time range filters for a job."""
        time_range_filters = []
        start_time, end_time = get_formatted_start_and_end_time(
            job=job, include_end_time_when_not_finished=False
        )
        if start_time:
            time_range_filters.append(f'timestamp>="{start_time}"')
        if end_time:
            time_range_filters.append(f'timestamp<="{end_time}"')
        return time_range_filters

    @classmethod
    def get_filter_string_for_job(
        cls,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
        agent_logs: bool = False,
        custom_label_filters: list[str] | None = None,
    ) -> str:
        """
        Generate the exact filter string used in the Google Cloud Console browser.

        Args:
            job: The GCSBatchJob object to filter by
            severity (str): Minimum severity level (e.g., "DEFAULT", "INFO", "WARNING", "ERROR")

        Returns:
            str: The browser-compatible filter string
        """
        project_id = GoogleUtils.get_project_id(job)
        log_path = "batch_agent_logs" if agent_logs else "batch_task_logs"
        filter_parts = [
            f'logName="projects/{project_id}/logs/{log_path}"',
        ]

        if custom_label_filters:
            filter_parts.extend(custom_label_filters)
        else:
            filter_parts.append(f'labels.job_uid="{job.uid}"')

        if severity:
            filter_parts.append(f"severity>={severity}")

        # Add time range filters using job's create_time and update_time
        time_range_filters = cls.get_time_range_filters(job)
        if time_range_filters:
            filter_parts.extend(time_range_filters)

        filter_str = " ".join(filter_parts)
        return filter_str

    @classmethod
    def get_cloud_logging_url(
        cls,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
        agent_logs: bool = False,
        custom_label_filters: dict[str, str] | None = None,
    ) -> str:
        """
        Generate a URL to the Google Cloud Logging console filtered for this job.

        Args:
            job (GCSBatchJob): The GCSBatchJob object to generate a URL for
            severity (str): Minimum severity level (e.g., "DEFAULT", "INFO", "WARNING", "ERROR")
            agent_logs (bool): Whether to include agent logs (default: False)
            custom_label_filters (Dict[str, str]): Optional mapping of label key to
                label value to filter the query by. If provided, overrides the
                job_uid filter.

        Returns:
            str: URL to the Cloud Logging console with filters applied
        """
        job_filters = []
        if custom_label_filters:
            job_filters.extend(
                [f'labels.{key}="{value}"' for key, value in custom_label_filters.items()]
            )
        else:
            job_filters.append(f'labels.job_uid="{job.uid}"')

        filter_str = cls.get_filter_string_for_job(job, severity, agent_logs, job_filters)
        # URL encode the filter string
        encoded_filter = quote(filter_str, safe="")
        project_id = GoogleUtils.get_project_id(job)
        # Construct the Cloud Logging console URL
        url = (
            f"https://console.cloud.google.com/logs/query;query={encoded_filter}"
            f"?project={project_id}"
        )
        return url

    def get_instance_id_from_logs(self, job: GCSBatchJob) -> str | None:
        """
        Get the first instance ID from Cloud Logging by querying batch agent logs.

        Instance information is extracted from resource.labels which contains:
        - instance_id: numeric instance ID
        - instance_name: instance name
        - zone: zone where the instance is running

        Args:
            job: The GCSBatchJob object to look up an instance for.

        Returns:
            The instance ID if one could be found in the logs, otherwise ``None``.

        * IMPORTANT: This is a hack to get the instance ID because the Compute Engine
          API is not always reachable (e.g. in restricted-VPC or limited-API
          environments) and the Batch API doesn't return the instance ID directly.
        Caveats: this only returns the first instance ID found in the logs (jobs
        currently have a single instance, so this would break if that changes), and
        it could fail if the log format changes.
        """

        # Query Cloud Logging for batch_agent_logs with gce_instance resource type
        # The resource.labels contain the instance information
        # Limit query to only return last 10 logs
        filter_str = (
            f'logName="projects/{self.config.project_id}/logs/batch_agent_logs" '
            f'AND labels.job_uid="{job.uid}" '
            f'AND resource.type="gce_instance" '
            f"AND resource.labels.instance_id:*"
        )
        time_range_filters = self.get_time_range_filters(job)
        if time_range_filters:
            filter_str += " " + " ".join(time_range_filters)

        # Query logs using the batch_logging client (limited to 10 results). This
        # lookup is a best-effort convenience, so a failed query (e.g. the caller
        # cannot read Cloud Logging) must not propagate.
        try:
            logs = self._query_cloud_logs(filter_str, max_results=10)
        except Exception as e:
            self.logging.debug(f"Could not look up the instance ID from logs: {e}")
            return None
        self.logging.debug(f"Found {len(logs)} logs with instance information")

        for log in logs:
            # Extract instance information from resource.labels
            resource = log.get("resource", {})
            if isinstance(resource, dict):
                resource_labels = resource.get("labels", {})
                if isinstance(resource_labels, dict):
                    instance_id = resource_labels.get("instance_id")
                    if instance_id:
                        return instance_id
        return None

    def _query_cloud_logs(
        self,
        filter_str: str,
        max_results: int
        | None = 1000,  # Limit to prevent overwhelming output - set to none to return all logs
    ) -> list[dict]:
        """
        Query Cloud Logging with the given filter.

        Args:
            filter_str (str): The filter string for the query
            max_results (int): Maximum number of log entries to return (default: None)

        Returns:
            List[dict]: List of log entries
        """
        try:
            # Use the Cloud Logging client to list log entries
            entries = self.cloud_logging_client.list_entries(
                filter_=filter_str,
                max_results=max_results,
                order_by=cloud_logging.DESCENDING,
            )

            logs = []
            for entry in entries:
                log_entry = {
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else "Unknown time",
                    "severity": entry.severity.name
                    if entry.severity and hasattr(entry.severity, "name")
                    else (str(entry.severity) if entry.severity else "INFO"),
                    "textPayload": entry.payload.get("textPayload", "")
                    if hasattr(entry.payload, "get")
                    else str(entry.payload),
                    "jsonPayload": entry.payload.get("jsonPayload", {})
                    if hasattr(entry.payload, "get")
                    else {},
                    "resource": {
                        "type": entry.resource.type if entry.resource else "unknown",
                        "labels": dict(entry.resource.labels)
                        if entry.resource and hasattr(entry.resource, "labels")
                        else {},
                    },
                }
                logs.append(log_entry)

            return logs

        except Exception as e:
            self.logging.error(f"Error querying Cloud Logging with filter '{filter_str}': {e}")
            raise

    def _sort_logs_chronologically(self, logs: list[dict]) -> list[dict]:
        """
        Sort logs in chronological order by timestamp.

        Args:
            logs (List[dict]): List of log entries

        Returns:
            List[dict]: Logs sorted chronologically (oldest first)
        """
        from datetime import datetime

        def get_timestamp(log):
            """Extract timestamp for sorting, handling various formats."""
            timestamp_str = log.get("timestamp", "")
            if not timestamp_str or timestamp_str == "Unknown time":
                return datetime.min  # Put unknown timestamps at the beginning

            try:
                # Try parsing ISO format timestamp
                if "T" in timestamp_str and "Z" in timestamp_str:
                    return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                elif "T" in timestamp_str:
                    return datetime.fromisoformat(timestamp_str)
                else:
                    # Fallback to string comparison
                    return datetime.min
            except (ValueError, TypeError):
                return datetime.min

        return sorted(logs, key=get_timestamp)

    def download_logs_for_job_with_time_range(
        self,
        job: GCSBatchJob,
        download_dir: str,
        severity: str = "DEFAULT",
    ):
        """
        Download logs for a job using the job's create_time and/or update_time as time filters.

        Args:
            job: The GCSBatchJob object to download logs for
            download_dir: Directory to save the logs
            severity: Minimum severity level for logs
        """

        self.download_logs_for_job(job, download_dir, severity)

    def print_logs_for_job_with_time_range(
        self,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
    ):
        """
        Print logs for a job using the job's create_time and/or update_time as time filters.

        Args:
            job: The GCSBatchJob object to print logs for
            severity: Minimum severity level for logs
        """

        self.print_logs_for_job(job, severity)
