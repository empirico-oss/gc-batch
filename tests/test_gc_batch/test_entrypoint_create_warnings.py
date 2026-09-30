"""Tests for the create-time warning about unreadable log destinations."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from google.cloud import batch_v1

from gc_batch.entrypoint import cli

WARNING_MARKER = "Cloud Logging usually cannot be read"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _created_job() -> batch_v1.Job:
    return batch_v1.Job(
        name="projects/test-project/locations/us-central1/jobs/my-job-1",
        uid="j-abc123",
        status=batch_v1.JobStatus(state=batch_v1.JobStatus.State.QUEUED),
    )


def _invoke(runner: CliRunner, *extra: str):
    """Run `create` with a mocked client, returning the click result."""
    with patch("gc_batch.entrypoint.create_client") as mock_create_client:
        client = MagicMock()
        client.create_job.return_value = _created_job()
        client.get_cloud_logging_url.return_value = "https://console.example/logs"
        mock_create_client.return_value = client
        # The gcloud account is resolved inside BatchJobConfig.apply_profile.
        with patch(
            "gc_batch.models.job_request.get_current_account",
            return_value="me@example.com",
        ):
            return runner.invoke(
                cli,
                [
                    "--project-id",
                    "test-project",
                    "create",
                    "--job-name",
                    "my-job",
                    "--docker-image",
                    "gcr.io/example/image:tag",
                    "--command",
                    "echo hi",
                    *extra,
                ],
            )


class TestUnreadableLogDestinationWarning:
    """`--logs-bucket` cannot be changed after creation, so warn while it still can."""

    def test_warns_for_all_of_us_without_a_logs_bucket(self, runner):
        result = _invoke(runner, "--job-profile", "all-of-us")

        assert result.exit_code == 0
        assert WARNING_MARKER in result.output
        assert "--logs-bucket" in result.output

    def test_explains_that_the_destination_cannot_be_changed_later(self, runner):
        result = _invoke(runner, "--job-profile", "all-of-us")

        assert "cannot" in result.output and "after" in result.output

    def test_no_warning_when_a_logs_bucket_is_given(self, runner):
        result = _invoke(
            runner, "--job-profile", "all-of-us", "--logs-bucket", "my-bucket/batch-logs"
        )

        assert result.exit_code == 0
        assert WARNING_MARKER not in result.output

    def test_no_warning_without_a_profile(self, runner):
        result = _invoke(runner)

        assert result.exit_code == 0
        assert WARNING_MARKER not in result.output

    def test_job_is_still_created(self, runner):
        """The warning is advisory: it must not block a valid job."""
        result = _invoke(runner, "--job-profile", "all-of-us")

        assert "Job created successfully" in result.output
        assert result.exit_code == 0


class TestCloudLoggingUrlIsAnnotated:
    """The success block prints a Cloud Logging URL that will not work here."""

    def test_url_carries_a_caveat_when_logging_is_unreadable(self, runner):
        result = _invoke(runner, "--job-profile", "all-of-us")

        assert "Cloud Logging URL:" in result.output
        assert "will most likely show nothing" in result.output

    def test_no_caveat_when_a_logs_bucket_is_used(self, runner):
        result = _invoke(
            runner, "--job-profile", "all-of-us", "--logs-bucket", "my-bucket/batch-logs"
        )

        assert "will most likely show nothing" not in result.output

    def test_no_caveat_without_a_profile(self, runner):
        result = _invoke(runner)

        assert "Cloud Logging URL:" in result.output
        assert "will most likely show nothing" not in result.output
