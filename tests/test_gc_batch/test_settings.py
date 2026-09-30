"""Unit tests for GCBatchSettings and its nested configuration models."""

from pathlib import Path

from gc_batch.settings import GCBatchSettings, JobProfile
from gc_batch.utils import resolve_created_by_label


class TestNeutralDefaults:
    def test_top_level_defaults(self):
        settings = GCBatchSettings()

        assert settings.job_name_prefix == ""
        assert settings.created_using_label == "gc-batch"
        assert settings.owner_email_env_vars == [
            "OWNER_EMAIL",
            "WORKBENCH_USER_EMAIL",
            "TERRA_USER_EMAIL",
            "USER",
        ]
        assert settings.default_project_id is None


class TestBuiltInJobProfiles:
    def test_all_of_us_profile_matches_exact_original_values(self):
        settings = GCBatchSettings()

        profile = settings.job_profiles["all-of-us"]

        assert profile == JobProfile(
            network="global/networks/network",
            subnetwork="regions/us-central1/subnetworks/subnetwork",
            use_private_address=True,
            regions=["us-central1"],
            service_account_from_gcloud=True,
            cloud_logging_unreadable=True,
        )

    def test_all_of_us_profile_declares_cloud_logging_unreadable(self):
        """Workspace service accounts cannot read Cloud Logging, so `create` warns."""
        assert GCBatchSettings().job_profiles["all-of-us"].cloud_logging_unreadable is True

    def test_cloud_logging_is_assumed_readable_by_default(self):
        assert JobProfile().cloud_logging_unreadable is False

    def test_user_profiles_merge_with_rather_than_replace_builtin(self):
        settings = GCBatchSettings(job_profiles={"custom": JobProfile(network="custom-network")})

        assert "all-of-us" in settings.job_profiles
        assert "custom" in settings.job_profiles
        assert settings.job_profiles["custom"].network == "custom-network"

    def test_user_profiles_can_override_builtin(self):
        settings = GCBatchSettings(
            job_profiles={"all-of-us": JobProfile(network="overridden-network")}
        )

        assert settings.job_profiles["all-of-us"].network == "overridden-network"
        assert settings.job_profiles["all-of-us"].use_private_address is False


class TestEnvVarOverride:
    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("GC_BATCH_JOB_NAME_PREFIX", "env-prefix-")

        settings = GCBatchSettings()

        assert settings.job_name_prefix == "env-prefix-"

    def test_nested_env_var_overrides_default(self, monkeypatch):
        """`env_nested_delimiter` resolves into nested models.

        Note the profile key is normalized to `my_vpc` (underscore), not `my-vpc`.
        """
        monkeypatch.setenv("GC_BATCH_JOB_PROFILES__MY_VPC__NETWORK", "env-nested-network")

        settings = GCBatchSettings()

        assert settings.job_profiles["my_vpc"].network == "env-nested-network"


class TestTomlFileOverride:
    def test_toml_file_overrides_default(self, tmp_path: Path):
        config_file = tmp_path / "gc-batch.toml"
        config_file.write_text(
            """
            job_name_prefix = "toml-prefix-"
            created_using_label = "toml-label"
            """
        )

        settings = GCBatchSettings.load(config_file=config_file)

        assert settings.job_name_prefix == "toml-prefix-"
        assert settings.created_using_label == "toml-label"

    def test_plain_constructor_does_not_read_toml_file(self, tmp_path: Path, monkeypatch):
        """Without calling `load()`, no TOML file is consulted, even if one exists."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "gc-batch.toml").write_text('created_using_label = "should-not-apply"\n')

        settings = GCBatchSettings()

        assert settings.created_using_label == "gc-batch"


class TestPrecedence:
    def test_constructor_beats_env_beats_toml_beats_default(self, tmp_path: Path, monkeypatch):
        config_file = tmp_path / "gc-batch.toml"
        config_file.write_text(
            """
            job_name_prefix = "toml-prefix-"
            created_using_label = "toml-label"
            default_project_id = "toml-project"
            """
        )

        # No overrides: TOML value wins over the default.
        settings = GCBatchSettings.load(config_file=config_file)
        assert settings.default_project_id == "toml-project"

        # Env var beats TOML.
        monkeypatch.setenv("GC_BATCH_DEFAULT_PROJECT_ID", "env-project")
        settings = GCBatchSettings.load(config_file=config_file)
        assert settings.default_project_id == "env-project"

        # Explicit constructor argument beats env var and TOML.
        settings = GCBatchSettings.load(config_file=config_file, default_project_id="ctor-project")
        assert settings.default_project_id == "ctor-project"


class TestRemovedSettingsAreIgnored:
    def test_stale_config_file_sections_do_not_raise(self, tmp_path: Path):
        """A config file still carrying the removed sections must load, not raise.

        `run_label_keys` and `dashboards` were removed in 0.2.0. `extra="ignore"`
        means an old config file keeps working instead of failing validation.
        """
        config_file = tmp_path / "gc-batch.toml"
        config_file.write_text(
            """
            job_name_prefix = "toml-prefix-"

            [run_label_keys]
            prefix = "my-orchestrator-"

            [dashboards.project_dashboard_ids]
            "my-project" = "00000000-0000-0000-0000-000000000000"
            """
        )

        # `load()` itself is the assertion: without `extra="ignore"` the unknown
        # top-level sections would raise a pydantic validation error here.
        settings = GCBatchSettings.load(config_file=config_file)

        # The recognized key still applies, and the removed ones are not absorbed.
        assert settings.job_name_prefix == "toml-prefix-"
        assert "run_label_keys" not in settings.model_dump()
        assert "dashboards" not in settings.model_dump()


class TestOwnerEmailEnvVarDefaults:
    """The ``created-by`` label must work where ``$USER`` is unset.

    The All of Us Researcher Workbench does not set ``$USER``, so before these
    defaults every job created there was labelled ``created-by=unknown``, which
    made ``list-my-jobs`` match nothing.
    """

    def test_all_of_us_owner_email_is_used_when_user_is_unset(self, monkeypatch):
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.setenv("OWNER_EMAIL", "researcher@researchallofus.org")

        created_by = resolve_created_by_label(GCBatchSettings().owner_email_env_vars)

        assert created_by == "researcher"

    def test_owner_email_takes_precedence_over_user(self, monkeypatch):
        monkeypatch.setenv("USER", "jupyter")
        monkeypatch.setenv("OWNER_EMAIL", "researcher@researchallofus.org")

        created_by = resolve_created_by_label(GCBatchSettings().owner_email_env_vars)

        assert created_by == "researcher"

    def test_workbench_and_terra_aliases_are_checked(self, monkeypatch):
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("OWNER_EMAIL", raising=False)
        monkeypatch.setenv("TERRA_USER_EMAIL", "first.last@researchallofus.org")

        created_by = resolve_created_by_label(GCBatchSettings().owner_email_env_vars)

        assert created_by == "first-last"

    def test_user_is_still_honoured_outside_all_of_us(self, monkeypatch):
        for var in ("OWNER_EMAIL", "WORKBENCH_USER_EMAIL", "TERRA_USER_EMAIL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("USER", "someone")

        created_by = resolve_created_by_label(GCBatchSettings().owner_email_env_vars)

        assert created_by == "someone"

    def test_unknown_when_nothing_is_set(self, monkeypatch):
        for var in ("OWNER_EMAIL", "WORKBENCH_USER_EMAIL", "TERRA_USER_EMAIL", "USER"):
            monkeypatch.delenv(var, raising=False)

        created_by = resolve_created_by_label(GCBatchSettings().owner_email_env_vars)

        assert created_by == "unknown"
