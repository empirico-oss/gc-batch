"""Tests for how `create` picks the job's region and Batch location."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from google.cloud import batch_v1

from gc_batch.entrypoint import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _invoke(runner, global_args=(), create_args=(), detected=None):
    """Run `create` with a mocked client.

    Returns:
        The click result, the location the client was built for, the submitted
        JobRequest, and the region-detection mock.
    """
    with (
        patch("gc_batch.entrypoint.create_client") as mock_create_client,
        patch("gc_batch.models.job_request.get_current_account", return_value="me@x.org"),
        patch("gc_batch.entrypoint.get_current_region", return_value=detected) as detect,
    ):
        client = MagicMock()
        client.create_job.return_value = batch_v1.Job(name="projects/p/locations/l/jobs/j")
        mock_create_client.return_value = client
        result = runner.invoke(
            cli,
            [
                "--project-id",
                "p",
                *global_args,
                "create",
                "--job-name",
                "j",
                "--docker-image",
                "img",
                "--command",
                "true",
                "--logs-bucket",
                "b/logs",
                *create_args,
            ],
        )
    location = mock_create_client.call_args.args[0] if mock_create_client.called else None
    request = client.create_job.call_args.args[0] if client.create_job.called else None
    return result, location, request, detect


AOU = ("--job-profile", "all-of-us")


class TestCreateRegion:
    def test_all_of_us_uses_detected_region(self, runner):
        result, location, request, _ = _invoke(runner, create_args=AOU, detected="us-east1")

        assert result.exit_code == 0, result.output
        assert "Detected region: us-east1" in result.output
        assert location == "us-east1"
        assert request.config.regions == ["us-east1"]
        assert request.config.subnetwork == "regions/us-east1/subnetworks/subnetwork"

    def test_all_of_us_falls_back_to_us_central1_with_a_warning(self, runner):
        result, location, request, _ = _invoke(runner, create_args=AOU)

        assert result.exit_code == 0, result.output
        assert "Could not detect the region" in result.output
        assert location == "us-central1"
        assert request.config.subnetwork == "regions/us-central1/subnetworks/subnetwork"

    @pytest.mark.parametrize(
        ("global_args", "create_args"),
        [
            (("--location", "us-west1"), AOU),
            ((), (*AOU, "--location", "us-west1")),
        ],
        ids=["global-option", "create-option"],
    )
    def test_location_overrides_detection(self, runner, global_args, create_args):
        result, location, request, detect = _invoke(
            runner, global_args, create_args, detected="us-east1"
        )

        assert result.exit_code == 0, result.output
        detect.assert_not_called()
        assert location == "us-west1"
        assert request.config.regions == ["us-west1"]
        assert request.config.subnetwork == "regions/us-west1/subnetworks/subnetwork"

    def test_create_location_beats_global_location(self, runner):
        _, location, _, _ = _invoke(runner, ("--location", "us-east1"), ("--location", "us-west1"))

        assert location == "us-west1"

    def test_detects_region_once(self, runner):
        _, _, _, detect = _invoke(runner, create_args=AOU, detected="us-east1")

        detect.assert_called_once()

    def test_without_profile_uses_detected_region(self, runner):
        result, location, request, _ = _invoke(runner, detected="us-east1")

        assert result.exit_code == 0, result.output
        assert location == "us-east1"
        assert request.config.regions is None

    def test_without_profile_or_detection_defaults_to_us_central1(self, runner):
        result, location, _, _ = _invoke(runner)

        assert result.exit_code == 0, result.output
        assert location == "us-central1"

    def test_profile_region_beats_detection(self, runner, tmp_path):
        config_file = tmp_path / "gc-batch.toml"
        config_file.write_text('[job_profiles.west]\nregions = ["us-west1"]\n')

        result, location, request, detect = _invoke(
            runner,
            ("--config-file", str(config_file)),
            ("--job-profile", "west"),
            detected="us-east1",
        )

        assert result.exit_code == 0, result.output
        detect.assert_not_called()
        assert location == "us-west1"
        assert request.config.regions == ["us-west1"]


@pytest.mark.parametrize(
    "command",
    [
        ["list-jobs"],
        ["list-my-jobs"],
        ["status", "--job-name", "j"],
        ["logs", "print", "--job-name", "j"],
        ["cancel", "--job-name", "j"],
    ],
    ids=lambda command: command[0],
)
class TestOtherCommandsRegion:
    def _invoke(self, runner, command, global_args=(), detected=None):
        with (
            patch("gc_batch.entrypoint.create_client") as mock_create_client,
            patch("gc_batch.entrypoint.get_current_region", return_value=detected) as detect,
        ):
            mock_create_client.return_value = MagicMock()
            result = runner.invoke(cli, ["--project-id", "p", *global_args, *command])
        return result, mock_create_client.call_args.args[0], detect

    def test_uses_detected_region(self, runner, command):
        result, location, _ = self._invoke(runner, command, detected="us-east1")

        assert location == "us-east1"
        assert "Detected region: us-east1" in result.output

    def test_location_overrides_detection(self, runner, command):
        _, location, detect = self._invoke(
            runner, command, ("--location", "us-west1"), detected="us-east1"
        )

        detect.assert_not_called()
        assert location == "us-west1"

    def test_defaults_to_us_central1_when_detection_fails(self, runner, command):
        _, location, _ = self._invoke(runner, command)

        assert location == "us-central1"
