"""Tests for GCBatchClient, focused on list_jobs filtering behavior."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import PermissionDenied
from google.cloud import batch_v1
from google.cloud.batch_v1.types import Job as GCSBatchJob
from google.cloud.batch_v1.types import JobStatus

from gc_batch.client import GCBatchClient
from gc_batch.constants import Constants
from gc_batch.models.batch_config import BatchClientConfig
from gc_batch.models.job_request import BatchJobConfig, JobRequest


@pytest.fixture
def client():
    config = BatchClientConfig(project_id="test-project", location="us-central1")
    with (
        patch("gc_batch.client.batch_v1.BatchServiceClient"),
        patch("gc_batch.batch_logging.cloud_logging.Client"),
    ):
        return GCBatchClient(config)


def _make_job(short_name: str, state=JobStatus.State.SUCCEEDED) -> MagicMock:
    """Create a mock GCSBatchJob with the given short name."""
    job = MagicMock(spec=GCSBatchJob)
    job.name = f"projects/test-project/locations/us-central1/jobs/{short_name}"
    job.status = MagicMock()
    job.status.state = state
    job.create_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    job.update_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    return job


class TestListJobsNameFilter:
    def test_name_filter_returns_matching_job(self, client):
        job_a = _make_job("my-job-a-1234567890")
        job_b = _make_job("my-job-b-9876543210")
        client._list_jobs = MagicMock(return_value=[job_a, job_b])

        result = client.list_jobs(name="my-job-a-1234567890")

        assert result == [job_a]

    def test_name_filter_returns_empty_when_no_match(self, client):
        job_a = _make_job("my-job-a-1234567890")
        client._list_jobs = MagicMock(return_value=[job_a])

        result = client.list_jobs(name="my-job-nonexistent-0000000000")

        assert result == []

    def test_name_filter_does_not_pass_name_to_api(self, client):
        """The name filter must not be included in the API filter string."""
        client._list_jobs = MagicMock(return_value=[])

        client.list_jobs(name="my-job-a-1234567890")

        # Called with no filter string (or no positional arg containing "name=")
        args, kwargs = client._list_jobs.call_args
        filter_arg = args[0] if args else kwargs.get("filter_string")
        assert filter_arg is None or "name=" not in filter_arg

    def test_name_filter_combined_with_status(self, client):
        job_a = _make_job("my-job-a", state=JobStatus.State.SUCCEEDED)
        job_b = _make_job("my-job-b", state=JobStatus.State.FAILED)
        client._list_jobs = MagicMock(return_value=[job_a, job_b])

        result = client.list_jobs(name="my-job-a", status="SUCCEEDED")

        # API should have been called with a status filter
        args, _ = client._list_jobs.call_args
        assert 'status.state="SUCCEEDED"' in args[0]
        assert result == [job_a]

    def test_no_name_filter_returns_all_jobs(self, client):
        job_a = _make_job("my-job-a-1234567890")
        job_b = _make_job("my-job-b-9876543210")
        client._list_jobs = MagicMock(return_value=[job_a, job_b])

        result = client.list_jobs()

        assert result == [job_a, job_b]


def _make_job_request(**config_overrides) -> JobRequest:
    """Build a minimal JobRequest with the given config overrides."""
    config = BatchJobConfig(
        machine_type="e2-standard-2",
        boot_disk_type="pd-balanced",
        **config_overrides,
    )
    return JobRequest(
        job_name="logs-test",
        docker_image="python:3.12",
        command="echo hi",
        config=config,
    )


class TestLogsPolicy:
    def test_defaults_to_cloud_logging(self, client):
        """Without a logs_bucket, the job writes to Cloud Logging."""
        job = client._create_job_spec(_make_job_request())

        assert job.logs_policy.destination == batch_v1.LogsPolicy.Destination.CLOUD_LOGGING

    def test_logs_bucket_routes_to_path_destination(self, client):
        """With a logs_bucket, the job writes logs to the mounted bucket path."""
        job = client._create_job_spec(_make_job_request(logs_bucket="my-bucket/batch-logs"))

        assert job.logs_policy.destination == batch_v1.LogsPolicy.Destination.PATH
        # Logs are written directly to the mounted bucket path (trailing slash
        # required so Batch treats it as the bucket mount's root directory).
        assert job.logs_policy.logs_path == f"{Constants.LOGS_MOUNT_POINT}/"

    def test_logs_bucket_is_mounted_as_volume(self, client):
        """The logs bucket is mounted on the VM but not into the container."""
        job = client._create_job_spec(_make_job_request(logs_bucket="my-bucket/batch-logs"))

        volumes = job.task_groups[0].task_spec.volumes
        logs_volumes = [v for v in volumes if v.mount_path == Constants.LOGS_MOUNT_POINT]
        assert len(logs_volumes) == 1
        # Logs are written to a per-job subfolder under the provided bucket path.
        assert logs_volumes[0].gcs.remote_path == f"my-bucket/batch-logs/{job.name}"
        # gcsfuse needs --implicit-dirs so a not-yet-existing subfolder is usable.
        assert "--implicit-dirs" in logs_volumes[0].mount_options

    def test_logs_billing_project_sets_mount_option(self, client):
        """A logs billing project is passed through as a gcsfuse mount option."""
        job = client._create_job_spec(
            _make_job_request(
                logs_bucket="my-bucket/batch-logs",
                logs_billing_project="my-billing-project",
            )
        )

        volumes = job.task_groups[0].task_spec.volumes
        logs_volume = next(v for v in volumes if v.mount_path == Constants.LOGS_MOUNT_POINT)
        assert "--billing-project=my-billing-project" in logs_volume.mount_options


def _make_failed_job(
    state=JobStatus.State.FAILED,
    logs_bucket: str | None = None,
    image_uri: str = "us-docker.pkg.dev/proj/repo/image:missing-tag",
) -> batch_v1.Job:
    """Build a realistic failed job, optionally in GCS (PATH) logging mode."""
    volumes = []
    destination = batch_v1.LogsPolicy.Destination.CLOUD_LOGGING
    if logs_bucket:
        volumes.append(
            batch_v1.Volume(
                gcs=batch_v1.GCS(remote_path=logs_bucket),
                mount_path=Constants.LOGS_MOUNT_POINT,
            )
        )
        destination = batch_v1.LogsPolicy.Destination.PATH

    return batch_v1.Job(
        name="projects/test-project/locations/us-central1/jobs/my-job-1",
        uid="j-abc123",
        task_groups=[
            batch_v1.TaskGroup(
                task_spec=batch_v1.TaskSpec(
                    volumes=volumes,
                    runnables=[
                        batch_v1.Runnable(
                            container=batch_v1.Runnable.Container(image_uri=image_uri)
                        )
                    ],
                )
            )
        ],
        logs_policy=batch_v1.LogsPolicy(destination=destination),
        status=batch_v1.JobStatus(
            state=state,
            status_events=[
                batch_v1.StatusEvent(
                    description="Job failed due to task failure. Task task/j-abc123-group0-0/0/0 "
                    "failed with exit code 1"
                )
            ],
        ),
    )


class TestPreContainerFailureInference:
    def test_infers_image_pull_failure_when_no_gcs_objects_exist(self, client):
        job = _make_failed_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.has_log_objects = MagicMock(return_value=False)

        message = client.get_failure_message(job)

        assert "Inference" in message
        assert "container never started" in message
        assert "us-docker.pkg.dev/proj/repo/image:missing-tag" in message

    def test_inference_is_labelled_as_not_reported_by_batch(self, client):
        job = _make_failed_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.has_log_objects = MagicMock(return_value=False)

        assert "not reported by Batch" in client.get_failure_message(job)

    def test_no_inference_when_gcs_log_objects_exist(self, client):
        job = _make_failed_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.has_log_objects = MagicMock(return_value=True)

        assert "Inference" not in client.get_failure_message(job)

    def test_infers_from_empty_cloud_logging_result(self, client):
        job = _make_failed_job()
        client.batch_logging._query_cloud_logs = MagicMock(return_value=[])

        assert "container never started" in client.get_failure_message(job)

    def test_no_inference_when_task_logs_exist_in_cloud_logging(self, client):
        job = _make_failed_job()
        client.batch_logging._query_cloud_logs = MagicMock(
            return_value=[{"textPayload": "some task output"}]
        )

        assert "Inference" not in client.get_failure_message(job)

    def test_no_inference_when_the_log_probe_itself_fails(self, client):
        """A 403 means we cannot tell, so we must not guess."""
        job = _make_failed_job()
        client.batch_logging._query_cloud_logs = MagicMock(
            side_effect=PermissionDenied("Permission denied for all log views")
        )

        message = client.get_failure_message(job)

        assert "Inference" not in message
        assert "exit code 1" in message

    def test_no_inference_for_a_successful_job(self, client):
        job = _make_failed_job(state=JobStatus.State.SUCCEEDED)
        client.batch_logging._query_cloud_logs = MagicMock(return_value=[])

        assert "Inference" not in client.get_failure_message(job)

    def test_failure_details_are_still_reported(self, client):
        job = _make_failed_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.has_log_objects = MagicMock(return_value=False)

        message = client.get_failure_message(job)

        assert "Job failed with state: FAILED" in message
        assert "exit code 1" in message
        assert "Job UID: j-abc123" in message


class TestJobLabels:
    """``created-by`` is set by the client, so library callers get it too.

    It used to be added by the CLI only, which meant jobs submitted through
    ``GCBatchClient`` were invisible to ``gc-batch list-my-jobs``.
    """

    def test_created_by_is_set_without_any_caller_labels(self, client, monkeypatch):
        monkeypatch.setenv("OWNER_EMAIL", "jane.doe@example.com")

        job = client._create_job_spec(_make_job_request())

        assert job.labels["created-by"] == "jane-doe"

    def test_created_by_falls_back_to_unknown(self, client, monkeypatch):
        for var in ("OWNER_EMAIL", "WORKBENCH_USER_EMAIL", "TERRA_USER_EMAIL", "USER"):
            monkeypatch.delenv(var, raising=False)

        job = client._create_job_spec(_make_job_request())

        assert job.labels["created-by"] == "unknown"

    def test_default_labels_are_present(self, client):
        job = client._create_job_spec(_make_job_request())

        assert job.labels["job-name"] == "logs-test"
        assert job.labels["created-using"] == "gc-batch"
        assert "created-at" in job.labels

    def test_caller_labels_are_merged(self, client, monkeypatch):
        monkeypatch.setenv("OWNER_EMAIL", "jane.doe@example.com")
        request = _make_job_request()
        request.labels = {"team": "data-science"}

        job = client._create_job_spec(request)

        assert job.labels["team"] == "data-science"
        assert job.labels["created-by"] == "jane-doe"

    def test_explicit_created_by_overrides_the_resolved_value(self, client, monkeypatch):
        """An explicitly passed label wins over the environment-derived default."""
        monkeypatch.setenv("OWNER_EMAIL", "jane.doe@example.com")
        request = _make_job_request()
        request.labels = {"created-by": "nightly-pipeline"}

        job = client._create_job_spec(request)

        assert job.labels["created-by"] == "nightly-pipeline"
