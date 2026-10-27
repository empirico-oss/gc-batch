"""Tests for BatchJobConfig, focused on job profile application."""

from unittest.mock import patch

import pytest

from gc_batch.constants import BatchProvisioningModel
from gc_batch.models.job_request import BatchJobConfig
from gc_batch.settings import GCBatchSettings, JobProfile


def _config(**overrides) -> BatchJobConfig:
    """Build a minimal BatchJobConfig with the given overrides."""
    return BatchJobConfig(
        machine_type="n2-standard-4",
        boot_disk_type="pd-balanced",
        **overrides,
    )


class TestApplyProfile:
    def test_networking_fields_are_applied(self):
        profile = JobProfile(
            network="global/networks/my-vpc",
            subnetwork="regions/us-central1/subnetworks/my-subnet",
            use_private_address=True,
            regions=["us-central1"],
        )

        config = _config().apply_profile(profile)

        assert config.network == "global/networks/my-vpc"
        assert config.subnetwork == "regions/us-central1/subnetworks/my-subnet"
        assert config.use_private_address is True
        assert config.regions == ["us-central1"]

    def test_returns_self_for_chaining(self):
        config = _config()

        assert config.apply_profile(JobProfile()) is config

    def test_unset_profile_fields_leave_existing_values_alone(self):
        config = _config(
            network="global/networks/preset",
            subnetwork="regions/us-central1/subnetworks/preset",
            regions=["us-west1"],
        )

        config.apply_profile(JobProfile(network="global/networks/from-profile"))

        assert config.network == "global/networks/from-profile"
        assert config.subnetwork == "regions/us-central1/subnetworks/preset"
        assert config.regions == ["us-west1"]

    def test_other_config_fields_are_untouched(self):
        config = _config(boot_disk_size=100, provisioning_model="SPOT")

        config.apply_profile(JobProfile(network="global/networks/my-vpc"))

        assert config.machine_type == "n2-standard-4"
        assert config.boot_disk_size == 100
        assert config.provisioning_model == BatchProvisioningModel.SPOT

    def test_service_account_resolved_from_gcloud(self):
        profile = JobProfile(service_account_from_gcloud=True)

        with patch(
            "gc_batch.models.job_request.get_current_account",
            return_value="user@example.com",
        ):
            config = _config().apply_profile(profile)

        assert config.service_account == "user@example.com"

    def test_raises_when_gcloud_account_is_unavailable(self):
        profile = JobProfile(service_account_from_gcloud=True)

        with (
            patch("gc_batch.models.job_request.get_current_account", return_value=None),
            pytest.raises(ValueError, match="gcloud auth login"),
        ):
            _config().apply_profile(profile)

    def test_service_account_untouched_when_profile_does_not_request_it(self):
        config = _config(service_account="preset@example.com")

        with patch("gc_batch.models.job_request.get_current_account") as get_account:
            config.apply_profile(JobProfile(network="global/networks/my-vpc"))

        get_account.assert_not_called()
        assert config.service_account == "preset@example.com"

    def test_built_in_all_of_us_profile(self):
        """The shipped profile is applied exactly as the CLI applies it."""
        profile = GCBatchSettings().job_profiles["all-of-us"]

        with (
            patch(
                "gc_batch.models.job_request.get_current_account",
                return_value="researcher@researchallofus.org",
            ),
            patch("gc_batch.models.job_request.get_current_region", return_value=None),
        ):
            config = _config().apply_profile(profile)

        assert config.network == "global/networks/network"
        assert config.subnetwork == "regions/us-central1/subnetworks/subnetwork"
        assert config.use_private_address is True
        assert config.regions == ["us-central1"]
        assert config.service_account == "researcher@researchallofus.org"


class TestApplyProfileRegion:
    _REGIONAL = JobProfile(
        subnetwork="regions/{region}/subnetworks/subnetwork",
        regions=["us-central1"],
        region_from_environment=True,
    )

    def test_detected_region_fills_regions_and_subnetwork(self):
        with patch("gc_batch.models.job_request.get_current_region", return_value="us-east1"):
            config = _config().apply_profile(self._REGIONAL)

        assert config.regions == ["us-east1"]
        assert config.subnetwork == "regions/us-east1/subnetworks/subnetwork"

    def test_falls_back_to_profile_regions_when_detection_fails(self):
        with patch("gc_batch.models.job_request.get_current_region", return_value=None):
            config = _config().apply_profile(self._REGIONAL)

        assert config.regions == ["us-central1"]
        assert config.subnetwork == "regions/us-central1/subnetworks/subnetwork"

    def test_explicit_region_overrides_detection(self):
        with patch("gc_batch.models.job_request.get_current_region") as detect:
            config = _config().apply_profile(self._REGIONAL, region="europe-west4")

        detect.assert_not_called()
        assert config.regions == ["europe-west4"]
        assert config.subnetwork == "regions/europe-west4/subnetworks/subnetwork"

    def test_explicit_region_overrides_non_detecting_profile(self):
        profile = JobProfile(regions=["us-central1"])

        config = _config().apply_profile(profile, region="us-west1")

        assert config.regions == ["us-west1"]

    def test_no_detection_unless_profile_requests_it(self):
        with patch("gc_batch.models.job_request.get_current_region") as detect:
            config = _config().apply_profile(JobProfile(regions=["us-west1"]))

        detect.assert_not_called()
        assert config.regions == ["us-west1"]

    def test_raises_when_placeholder_has_no_region(self):
        profile = JobProfile(subnetwork="regions/{region}/subnetworks/subnetwork")

        with pytest.raises(ValueError, match="needs a region"):
            _config().apply_profile(profile)

    def test_built_in_all_of_us_profile_follows_the_workspace_region(self):
        profile = GCBatchSettings().job_profiles["all-of-us"]

        with (
            patch("gc_batch.models.job_request.get_current_account", return_value="me@x.org"),
            patch("gc_batch.models.job_request.get_current_region", return_value="us-east4"),
        ):
            config = _config().apply_profile(profile)

        assert config.regions == ["us-east4"]
        assert config.subnetwork == "regions/us-east4/subnetworks/subnetwork"
