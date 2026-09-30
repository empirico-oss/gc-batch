"""Read Google Cloud Batch job logs from a GCS bucket.

When a job is created with ``--logs-bucket`` the Batch API writes its logs to a
mounted GCS bucket (``LogsPolicy.destination = PATH``) instead of Cloud Logging.
This module reads those objects back, which is the only log route available in
environments where the caller cannot read Cloud Logging at all (for example the
All of Us Researcher Workbench, where the workspace pet service account gets
``403 Permission denied for all log views``).

Classes:
    GCSLogReader: Reads and parses Batch log objects out of a GCS bucket.
    GCSLogLocation: The bucket, prefix and billing project a job's logs live at.
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

# google-cloud-storage ships no py.typed marker, so mypy cannot see it inside the
# google.cloud namespace package.
from google.cloud import storage  # type: ignore[attr-defined]
from google.cloud.batch_v1 import Volume
from google.cloud.batch_v1.types import Job as GCSBatchJob

from gc_batch.batch_logging import format_log_entry
from gc_batch.constants import Constants
from gc_batch.google_utils import GoogleUtils
from gc_batch.logger import Logger, get_logger
from gc_batch.models.batch_config import BatchClientConfig

#: Cloud Logging severity ordering, used for ``severity>=`` style thresholds.
SEVERITY_ORDER: dict[str, int] = {
    "DEFAULT": 0,
    "DEBUG": 100,
    "INFO": 200,
    "NOTICE": 300,
    "WARNING": 400,
    "ERROR": 500,
    "CRITICAL": 600,
    "ALERT": 700,
    "EMERGENCY": 800,
}

#: Batch writes three objects per task: ``output-`` is the superset of the other
#: two plus the agent's own lines.
_AGENT_STREAM = "output"
_TASK_STREAMS = ("stdout", "stderr")

#: Stream tag Batch puts on container output inside the ``output-`` objects. The
#: agent's own lines carry ``batch_agent_logs`` instead.
_TASK_LOG_TAG = "batch_task_logs"

#: ``{stream}-{job_uid}-group{GROUP}-{TASK}.log`` (the uid itself contains dashes).
_OBJECT_NAME_PATTERN = re.compile(
    r"^(?P<stream>output|stdout|stderr)-(?P<job_uid>.+)-group(?P<group>\d+)-(?P<task>\d+)\.log$"
)

#: ``[batch_task_logs]2026/09/18 16:11:40 ERROR: [task_id:…,runnable_index:0] message``
#: The ``[task_id:…]`` part is only present on task lines, not on agent lines.
_LOG_LINE_PATTERN = re.compile(
    r"^\[(?P<stream_tag>[a-z_]+)\]"
    r"(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?P<severity>[A-Z][A-Z0-9_]*): "
    r"(?:\[task_id:(?P<task_id>[^,\]]+),runnable_index:(?P<runnable_index>\d+)\] )?"
    r"(?P<message>.*)$"
)

_BATCH_TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M:%S"

#: Placeholder used by the Cloud Logging reader for entries without a timestamp.
_UNKNOWN_TIMESTAMP = "Unknown time"


@dataclass(frozen=True)
class GCSLogLocation:
    """Where a Batch job's logs are stored in GCS.

    Attributes:
        bucket: The GCS bucket name.
        prefix: The object prefix within the bucket (may be empty).
        billing_project: Billing project for requester-pays buckets, if the job
            was created with one.
    """

    bucket: str
    prefix: str
    billing_project: str | None = None

    @property
    def uri(self) -> str:
        """Return the ``gs://`` URI of the log directory."""
        if not self.prefix:
            return f"gs://{self.bucket}"
        return f"gs://{self.bucket}/{self.prefix}"


@dataclass(frozen=True)
class _LogObject:
    """A Batch log object, with the task and stream parsed out of its name."""

    blob: storage.Blob
    stream: str
    group: int
    task: int

    @property
    def name(self) -> str:
        """Return the object name, including its prefix."""
        return str(self.blob.name)

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Order objects by group, then task index, then stream name.

        The stream rank only matters in the fallback path where no ``output-``
        object exists; normally one ``output-`` object per task is read.
        """
        stream_rank = _TASK_STREAMS.index(self.stream) if self.stream in _TASK_STREAMS else 0
        return (self.group, self.task, stream_rank, self.name)


class GCSLogReader:
    """Read Google Cloud Batch logs written to a GCS bucket.

    The bucket and prefix are recovered from the job resource itself: the logs
    bucket is mounted at :attr:`Constants.LOGS_MOUNT_POINT`, so the volume's
    ``gcs.remote_path`` is the full ``bucket/prefix`` path Batch wrote to. No user
    input is needed beyond the job.

    Entries are returned in the same ``list[dict]`` shape that
    ``BatchLogging._query_cloud_logs`` produces, so the existing printing and
    downloading code paths work unchanged.

    Attributes:
        config: The BatchClientConfig with project settings.

    Example:
        ```python
        from gc_batch import BatchClientConfig
        from gc_batch.gcs_logging import GCSLogReader

        config = BatchClientConfig(project_id="my-project", location="us-central1")
        reader = GCSLogReader(config)

        job = client.get_job("my-job-1234567890")
        reader.print_logs_for_job(job)
        ```
    """

    def __init__(
        self,
        config: BatchClientConfig,
        storage_client: storage.Client | None = None,
        logger: Logger | None = None,
        log_level: int = logging.INFO,
    ):
        """Initialize the GCSLogReader.

        Args:
            config: Configuration with project_id and location settings.
            storage_client: Optional pre-built GCS client. When omitted, a client
                is created lazily on first use so that constructing the reader
                never requires credentials.
            logger: Optional logger to use instead of creating one.
            log_level: Level for the logger created when ``logger`` is omitted.
        """
        self.config = config
        self.logging = logger or get_logger(name="GCSLogReader", level=log_level)
        self._storage_client = storage_client

    @property
    def storage_client(self) -> storage.Client:
        """Return the GCS client, creating it on first access."""
        if self._storage_client is None:
            self._storage_client = storage.Client(project=self.config.project_id)
        return self._storage_client

    @staticmethod
    def uses_gcs_logs(job: GCSBatchJob) -> bool:
        """Report whether a job writes its logs to a mounted GCS bucket.

        Args:
            job: The job to inspect.

        Returns:
            ``True`` when the job has a logs volume mounted at
            :attr:`Constants.LOGS_MOUNT_POINT`, otherwise ``False``.
        """
        return GCSLogReader._find_logs_volume(job) is not None

    @staticmethod
    def resolve_log_location(job: GCSBatchJob) -> GCSLogLocation:
        """Resolve where a job's logs were written from the job resource.

        Args:
            job: The job to resolve the log location for.

        Returns:
            The :class:`GCSLogLocation` the Batch agent wrote logs to.

        Raises:
            ValueError: If the job has no logs volume, meaning it was not created
                with ``--logs-bucket`` and its logs are not in GCS.
        """
        volume = GCSLogReader._find_logs_volume(job)
        if volume is None:
            destination = job.logs_policy.destination.name if job.logs_policy else "UNSPECIFIED"
            raise ValueError(
                f"Job {GoogleUtils.get_job_name(job)} does not write logs to GCS: its "
                f"logs_policy.destination is {destination} and it has no volume mounted at "
                f"{Constants.LOGS_MOUNT_POINT}. Only jobs created with --logs-bucket can be "
                "read from GCS."
            )

        bucket, _, prefix = volume.gcs.remote_path.partition("/")
        billing_project = None
        for option in volume.mount_options:
            if option.startswith("--billing-project="):
                billing_project = option.split("=", 1)[1]

        return GCSLogLocation(
            bucket=bucket,
            prefix=prefix.strip("/"),
            billing_project=billing_project,
        )

    def list_log_objects(self, job: GCSBatchJob) -> list[str]:
        """List the names of the job's Batch log objects in GCS.

        Args:
            job: The job whose log objects should be listed.

        Returns:
            Sorted object names, including the prefix. Objects that do not match
            the Batch log naming scheme are excluded.

        Raises:
            ValueError: If the job does not write logs to GCS.
            google.api_core.exceptions.GoogleAPIError: If the listing fails.
        """
        return sorted(log_object.name for log_object in self._list_parsed_objects(job))

    def has_log_objects(self, job: GCSBatchJob) -> bool:
        """Report whether Batch wrote any log objects for the job.

        Zero objects for a failed job means Batch never got as far as running the
        container, which is the signal used to diagnose pre-container failures.

        Args:
            job: The job to check.

        Returns:
            ``True`` if at least one Batch log object exists.

        Raises:
            ValueError: If the job does not write logs to GCS.
            google.api_core.exceptions.GoogleAPIError: If the listing fails.
        """
        return bool(self._list_parsed_objects(job))

    def read_logs_for_job(
        self,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
        include_agent_logs: bool = False,
    ) -> list[dict]:
        """Read and parse all of a job's log entries from GCS.

        Entries are returned in the order Batch wrote them — object order within a
        task, tasks in index order, ``stdout`` before ``stderr`` — and are never
        re-sorted by timestamp, because Batch timestamps have only one-second
        resolution and re-sorting would scramble same-second output. No limit is
        applied: whole objects are read.

        Args:
            job: The job to read logs for.
            severity: Minimum Cloud Logging severity to include (``DEFAULT``
                keeps everything).
            include_agent_logs: When ``True``, keep the Batch agent's own lines
                alongside the container's output instead of dropping them. Both
                come from the same ``output-`` objects. The agent lines echo
                the full ``docker run`` invocation, so they repeat the job's own
                command text.

        Returns:
            Log entries with ``timestamp``, ``severity``, ``textPayload``,
            ``jsonPayload`` and ``resource`` keys, matching the shape the Cloud
            Logging reader returns.

        Raises:
            ValueError: If the job does not write logs to GCS, or ``severity`` is
                not a recognised Cloud Logging severity.
            google.api_core.exceptions.GoogleAPIError: If listing or downloading
                the log objects fails.
        """
        threshold = self._severity_rank(severity)
        location = self.resolve_log_location(job)
        bucket = self._get_bucket(location)

        # Entries come back in the order the Batch agent received them, which is
        # not necessarily the order the program wrote them: stdout is
        # block-buffered when it is not a terminal, so an unbuffered stderr line
        # is often recorded before stdout written earlier. That is Batch's
        # record, and it is reproduced rather than second-guessed.
        # Read the ``output-`` objects even when the caller does not want agent
        # lines. They hold stdout and stderr interleaved in true emission order,
        # whereas reading the ``stdout-``/``stderr-`` pair would place all of a
        # task's stderr after all of its stdout — Batch timestamps have only
        # one-second resolution, so that ordering cannot be repaired afterwards.
        # Agent lines are then dropped by stream tag, which also removes the
        # command echo in the ``output-`` header.
        parsed = self._list_parsed_objects(job, bucket=bucket, location=location)
        log_objects = [item for item in parsed if item.stream == _AGENT_STREAM]
        if not log_objects:
            # No superset object for this job; fall back to the per-stream pair.
            log_objects = [item for item in parsed if item.stream in _TASK_STREAMS]

        entries: list[dict] = []
        for log_object in sorted(log_objects, key=lambda item: item.sort_key):
            content = log_object.blob.download_as_bytes()
            entries.extend(self._parse_log_content(content, log_object))

        if not include_agent_logs:
            entries = [
                entry
                for entry in entries
                if entry["resource"]["labels"].get("stream_tag", _TASK_LOG_TAG) == _TASK_LOG_TAG
            ]

        self.logging.debug(
            f"Read {len(entries)} log entries from {len(log_objects)} objects at {location.uri}"
        )
        return [entry for entry in entries if self._entry_rank(entry) >= threshold]

    def print_logs_for_job(
        self,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
        include_agent_logs: bool = False,
    ) -> int:
        """Print a job's GCS-stored logs to the console.

        Args:
            job: The job to print logs for.
            severity: Minimum severity level to include.
            include_agent_logs: Whether to read the agent's ``output-`` objects.

        Returns:
            The number of entries printed. Zero means the read succeeded but the
            job produced no matching log entries.

        Raises:
            ValueError: If the job does not write logs to GCS, or the severity is
                not recognised.
            google.api_core.exceptions.GoogleAPIError: If the read fails.
        """
        location = self.resolve_log_location(job)
        entries = self.read_logs_for_job(job, severity, include_agent_logs)
        if not entries:
            print(f"No log entries found for job {job.name} in {location.uri}")
            return 0

        print(f"\n{'=' * 80}")
        print(f"LOGS FOR JOB: {job.name} (from {location.uri})")
        print(f"{'=' * 80}")
        for entry in entries:
            print(format_log_entry(entry))
        return len(entries)

    def download_logs_for_job(
        self,
        job: GCSBatchJob,
        download_dir: str,
        severity: str = "DEFAULT",
        include_agent_logs: bool = False,
    ) -> int:
        """Download a job's GCS-stored logs into a single local file.

        Args:
            job: The job to download logs for.
            download_dir: Directory to write the log file into. Created if needed.
            severity: Minimum severity level to include.
            include_agent_logs: Whether to read the agent's ``output-`` objects.

        Returns:
            The number of entries written. Zero means the read succeeded but the
            job produced no matching log entries, and no file is written.

        Raises:
            ValueError: If the job does not write logs to GCS, or the severity is
                not recognised.
            google.api_core.exceptions.GoogleAPIError: If the read fails.
            OSError: If the log file cannot be written.
        """
        location = self.resolve_log_location(job)
        entries = self.read_logs_for_job(job, severity, include_agent_logs)
        if not entries:
            self.logging.warning(f"No log entries found for job {job.name} in {location.uri}")
            print(f"No log entries found for job {job.name} in {location.uri}")
            return 0

        os.makedirs(download_dir, exist_ok=True)
        log_file = os.path.join(download_dir, f"{GoogleUtils.get_job_name(job)}.log")
        with open(log_file, "w") as handle:
            for entry in entries:
                handle.write(f"{format_log_entry(entry)}\n")

        self.logging.debug(f"Downloaded {len(entries)} log entries to {log_file}")
        print(f"Downloaded {len(entries)} log entries to {log_file}")
        return len(entries)

    @staticmethod
    def _find_logs_volume(job: GCSBatchJob) -> Volume | None:
        """Return the job's GCS logs volume, or ``None`` if it has none."""
        if not job.task_groups:
            return None
        for volume in job.task_groups[0].task_spec.volumes:
            if volume.mount_path == Constants.LOGS_MOUNT_POINT and volume.gcs.remote_path:
                return volume
        return None

    def _get_bucket(self, location: GCSLogLocation) -> storage.Bucket:
        """Return the bucket handle, honouring requester-pays billing."""
        return self.storage_client.bucket(location.bucket, user_project=location.billing_project)

    def _list_parsed_objects(
        self,
        job: GCSBatchJob,
        bucket: storage.Bucket | None = None,
        location: GCSLogLocation | None = None,
    ) -> list[_LogObject]:
        """List the job's Batch log objects, ignoring anything else in the prefix."""
        location = location or self.resolve_log_location(job)
        bucket = bucket if bucket is not None else self._get_bucket(location)
        list_prefix = f"{location.prefix}/" if location.prefix else None

        log_objects = []
        for blob in bucket.list_blobs(prefix=list_prefix):
            base_name = blob.name.rsplit("/", 1)[-1]
            match = _OBJECT_NAME_PATTERN.match(base_name)
            if match is None:
                continue
            log_objects.append(
                _LogObject(
                    blob=blob,
                    stream=match.group("stream"),
                    group=int(match.group("group")),
                    task=int(match.group("task")),
                )
            )
        return log_objects

    def _parse_log_content(self, content: bytes, log_object: _LogObject) -> list[dict]:
        """Parse one log object's bytes into log entries.

        Decoding is lossy on purpose: a job that writes binary output must not
        break log retrieval.
        """
        text = content.decode("utf-8", errors="replace")
        if not text:
            return []

        entries: list[dict] = []
        for raw_line in text.split("\n"):
            line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
            match = _LOG_LINE_PATTERN.match(line)
            if match is None:
                if entries:
                    # Not a new entry: a continuation of the previous message.
                    entries[-1]["textPayload"] += f"\n{line}"
                elif line:
                    entries.append(self._make_entry(log_object, message=line))
                continue
            entries.append(
                self._make_entry(
                    log_object,
                    message=match.group("message"),
                    timestamp=match.group("timestamp"),
                    severity=match.group("severity"),
                    stream_tag=match.group("stream_tag"),
                    task_id=match.group("task_id"),
                    runnable_index=match.group("runnable_index"),
                )
            )
        return entries

    def _make_entry(
        self,
        log_object: _LogObject,
        message: str,
        timestamp: str | None = None,
        severity: str | None = None,
        stream_tag: str | None = None,
        task_id: str | None = None,
        runnable_index: str | None = None,
    ) -> dict:
        """Build a Cloud-Logging-shaped entry dict for one parsed log line."""
        labels = {
            "stream": log_object.stream,
            "object": log_object.name,
        }
        if stream_tag:
            labels["stream_tag"] = stream_tag
        if task_id:
            labels["task_id"] = task_id
        if runnable_index is not None:
            labels["runnable_index"] = runnable_index

        return {
            "timestamp": self._format_timestamp(timestamp),
            "severity": severity or "DEFAULT",
            "textPayload": message,
            "jsonPayload": {},
            "resource": {"type": "gcs_log_object", "labels": labels},
        }

    @staticmethod
    def _format_timestamp(timestamp: str | None) -> str:
        """Convert a Batch log timestamp to an ISO 8601 UTC string.

        Batch writes timezone-less timestamps at one-second resolution; they are
        UTC.
        """
        if not timestamp:
            return _UNKNOWN_TIMESTAMP
        parsed = datetime.strptime(timestamp, _BATCH_TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
        return parsed.isoformat()

    @staticmethod
    def _severity_rank(severity: str) -> int:
        """Return the Cloud Logging rank of a requested severity threshold.

        Raises:
            ValueError: If the severity is not a Cloud Logging severity, rather
                than silently matching nothing.
        """
        if not severity:
            return SEVERITY_ORDER["DEFAULT"]
        rank = SEVERITY_ORDER.get(severity.upper())
        if rank is None:
            valid = ", ".join(SEVERITY_ORDER)
            raise ValueError(f"Unknown severity {severity!r}. Valid severities are: {valid}")
        return rank

    @staticmethod
    def _entry_rank(entry: dict) -> int:
        """Return the rank of an entry's severity, treating unknowns as DEFAULT."""
        return SEVERITY_ORDER.get(str(entry.get("severity", "")).upper(), SEVERITY_ORDER["DEFAULT"])
