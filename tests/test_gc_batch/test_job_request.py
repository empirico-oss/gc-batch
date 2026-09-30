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

        with patch(
            "gc_batch.models.job_request.get_current_account",
            return_value="researcher@researchallofus.org",
        ):
            config = _config().apply_profile(profile)

        assert config.network == "global/networks/network"
        assert config.subnetwork == "regions/us-central1/subnetworks/subnetwork"
        assert config.use_private_address is True
        assert config.regions == ["us-central1"]
        assert config.service_account == "researcher@researchallofus.org"
