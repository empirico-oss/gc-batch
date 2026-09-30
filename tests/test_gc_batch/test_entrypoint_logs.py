"""Tests for the exit-code contract of the `logs` command."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from google.api_core.exceptions import PermissionDenied
from google.cloud import batch_v1

from gc_batch.constants import Constants
from gc_batch.entrypoint import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_job(logs_bucket: str | None = None) -> batch_v1.Job:
    volumes = []
    if logs_bucket:
        volumes.append(
            batch_v1.Volume(
                gcs=batch_v1.GCS(remote_path=logs_bucket),
                mount_path=Constants.LOGS_MOUNT_POINT,
            )
        )
    destination = (
        batch_v1.LogsPolicy.Destination.PATH
        if logs_bucket
        else batch_v1.LogsPolicy.Destination.CLOUD_LOGGING
    )
    return batch_v1.Job(
        name="projects/test-project/locations/us-central1/jobs/my-job-1",
        uid="j-abc123",
        task_groups=[batch_v1.TaskGroup(task_spec=batch_v1.TaskSpec(volumes=volumes))],
        logs_policy=batch_v1.LogsPolicy(destination=destination),
        allocation_policy=batch_v1.AllocationPolicy(
            instances=[
                batch_v1.AllocationPolicy.InstancePolicyOrTemplate(
                    policy=batch_v1.AllocationPolicy.InstancePolicy(machine_type="e2-standard-2")
                )
            ]
        ),
    )


def _invoke(runner: CliRunner, client: MagicMock, *args: str):
    with patch("gc_batch.entrypoint.create_client", return_value=client):
        return runner.invoke(
            cli, ["--project-id", "test-project", "logs", *args], catch_exceptions=False
        )


class TestLogsExitCode:
    def test_exits_zero_when_the_query_succeeds_with_no_entries(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job()
        client.batch_logging.print_logs_for_job.return_value = 0

        result = _invoke(runner, client, "print", "--job-name", "my-job-1")

        assert result.exit_code == 0

    def test_exits_non_zero_when_the_query_fails(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job()
        client.batch_logging.print_logs_for_job.side_effect = PermissionDenied(
            "Permission denied for all log views"
        )

        result = _invoke(runner, client, "print", "--job-name", "my-job-1")

        assert result.exit_code == 1
        assert "Permission denied for all log views" in result.output

    def test_permission_denied_names_the_logs_bucket_alternative(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job()
        client.batch_logging.print_logs_for_job.side_effect = PermissionDenied(
            "Permission denied for all log views"
        )

        result = _invoke(runner, client, "print", "--job-name", "my-job-1")

        assert "--logs-bucket" in result.output
        assert "cannot read Cloud Logging" in result.output

    def test_download_failure_exits_non_zero(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job()
        client.batch_logging.download_logs_for_job.side_effect = PermissionDenied("nope")

        result = _invoke(
            runner, client, "download", "--job-name", "my-job-1", "--download-dir", "."
        )

        assert result.exit_code == 1

    def test_invalid_severity_exits_non_zero(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.print_logs_for_job.side_effect = ValueError(
            "Unknown severity 'BOGUS'. Valid severities are: DEFAULT, DEBUG"
        )

        result = _invoke(runner, client, "print", "--job-name", "my-job-1", "--severity", "BOGUS")

        assert result.exit_code == 1
        assert "BOGUS" in result.output


class TestLogsDestinationRouting:
    def test_path_mode_job_is_read_from_gcs(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.print_logs_for_job.return_value = 3

        result = _invoke(runner, client, "print", "--job-name", "my-job-1")

        assert result.exit_code == 0
        client.gcs_logging.print_logs_for_job.assert_called_once()
        client.batch_logging.print_logs_for_job.assert_not_called()

    def test_cloud_logging_job_is_read_from_cloud_logging(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job()
        client.batch_logging.print_logs_for_job.return_value = 3

        result = _invoke(runner, client, "print", "--job-name", "my-job-1")

        assert result.exit_code == 0
        client.batch_logging.print_logs_for_job.assert_called_once()
        client.gcs_logging.print_logs_for_job.assert_not_called()

    def test_path_mode_download_is_read_from_gcs(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.gcs_logging.download_logs_for_job.return_value = 2

        result = _invoke(
            runner, client, "download", "--job-name", "my-job-1", "--download-dir", "."
        )

        assert result.exit_code == 0
        client.gcs_logging.download_logs_for_job.assert_called_once()
        client.batch_logging.download_logs_for_job.assert_not_called()


def _invoke_status(runner: CliRunner, client: MagicMock, *args: str):
    with patch("gc_batch.entrypoint.create_client", return_value=client):
        return runner.invoke(
            cli, ["--project-id", "test-project", "status", *args], catch_exceptions=False
        )


class TestStatusLogHint:
    def test_path_mode_job_hint_points_at_the_bucket(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job(logs_bucket="logs-bucket/batch-logs/my-job-1")
        client.get_failure_message.return_value = "Job failed with state: FAILED"

        result = _invoke_status(runner, client, "--job-name", "my-job-1")

        assert result.exit_code == 0
        assert "gs://logs-bucket/batch-logs/my-job-1" in result.output
        assert "console.cloud.google.com/logs" not in result.output

    def test_cloud_logging_job_hint_points_at_the_console(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job()
        client.get_cloud_logging_url.return_value = (
            "https://console.cloud.google.com/logs/query;query=x?project=test-project"
        )

        result = _invoke_status(runner, client, "--job-name", "my-job-1")

        assert result.exit_code == 0
        assert "console.cloud.google.com/logs" in result.output

    def test_both_destinations_recommend_logs_print(self, runner):
        client = MagicMock()
        client.get_job.return_value = _make_job(logs_bucket="logs-bucket/batch-logs/my-job-1")

        result = _invoke_status(runner, client, "--job-name", "my-job-1")

        assert "gc-batch logs print --job-name my-job-1" in result.output
