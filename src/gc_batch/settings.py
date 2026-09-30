"""Configuration settings for gc-batch.

This module centralizes every value that differs between deployments (project
ids, VPC network settings, etc.) into a single :class:`GCBatchSettings` object
with neutral defaults. A deployment adapts gc-batch entirely through
configuration -- environment variables or a TOML file -- with no code changes.

Resolution precedence (highest priority first):

1. Explicit constructor arguments, e.g. ``GCBatchSettings(job_name_prefix="foo-")``.
2. ``GC_BATCH_*`` environment variables (nested fields use ``__`` as a delimiter,
   e.g. ``GC_BATCH_JOB_PROFILES__MY_VPC__NETWORK``).
3. A TOML configuration file, only consulted via :meth:`GCBatchSettings.load`.
4. The neutral defaults defined in this module.

Classes:
    JobProfile: A named bundle of networking/VM settings for ``--job-profile``.
    GCBatchSettings: The top-level settings object.
"""

import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_CONFIG_FILE_ENV_VAR = "GC_BATCH_CONFIG_FILE"
_DEFAULT_CONFIG_FILE_NAME = "gc-batch.toml"
_XDG_CONFIG_HOME_ENV_VAR = "XDG_CONFIG_HOME"

# Sentinel distinguishing "no config file requested" (plain constructor use) from
# "use the standard discovery order" (GCBatchSettings.load() with no explicit path).
_TOML_DISABLED = object()


class JobProfile(BaseModel):
    """A named bundle of networking/VM settings applied via ``--job-profile``.

    Attributes:
        network: VPC network path for the VM (e.g. "global/networks/network").
        subnetwork: Subnetwork path for the VM.
        use_private_address: Whether to use a private IP (no external IP).
        regions: List of allowed regions for job placement.
        service_account_from_gcloud: Whether to resolve the job's service account
            from the current ``gcloud`` authenticated account.
        cloud_logging_unreadable: Whether callers in this environment are expected
            to be unable to read Cloud Logging. When ``True``, ``create`` warns if
            no ``--logs-bucket`` is given, because the job's logs would be written
            somewhere the user cannot read and the choice cannot be changed after
            the job is created.
    """

    network: str | None = None
    subnetwork: str | None = None
    use_private_address: bool = False
    regions: list[str] | None = None
    service_account_from_gcloud: bool = False
    cloud_logging_unreadable: bool = False


def _built_in_job_profiles() -> dict[str, JobProfile]:
    """Build the job profiles gc-batch ships with out of the box.

    Returns:
        A dictionary of built-in job profiles keyed by profile name.
    """
    return {
        "all-of-us": JobProfile(
            network="global/networks/network",
            subnetwork="regions/us-central1/subnetworks/subnetwork",
            use_private_address=True,
            regions=["us-central1"],
            service_account_from_gcloud=True,
            # Workspace service accounts have no Cloud Logging read access, so a
            # job that writes there produces logs nobody in the workspace can read.
            cloud_logging_unreadable=True,
        ),
    }


def _resolve_config_file(explicit: str | Path | None) -> Path | None:
    """Resolve which TOML config file to load, if any.

    Checks candidates in order and returns the first one that exists on disk:
    an explicit path, the ``GC_BATCH_CONFIG_FILE`` environment variable,
    ``./gc-batch.toml``, and finally ``$XDG_CONFIG_HOME/gc-batch/config.toml``
    (falling back to ``~/.config/gc-batch/config.toml`` when unset).

    Args:
        explicit: An explicit path passed by the caller, if any.

    Returns:
        The resolved path if a candidate exists, otherwise ``None``.
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))

    env_path = os.getenv(_CONFIG_FILE_ENV_VAR)
    if env_path:
        candidates.append(Path(env_path))

    candidates.append(Path(_DEFAULT_CONFIG_FILE_NAME))

    xdg_config_home = os.getenv(_XDG_CONFIG_HOME_ENV_VAR)
    if xdg_config_home:
        candidates.append(Path(xdg_config_home) / "gc-batch" / "config.toml")
    else:
        candidates.append(Path.home() / ".config" / "gc-batch" / "config.toml")

    for candidate in candidates:
        if candidate.expanduser().is_file():
            return candidate

    return None


class GCBatchSettings(BaseSettings):
    """Top-level configuration for gc-batch.

    All fields have neutral defaults. Deployment-specific behavior is supplied
    through ``GC_BATCH_*`` environment variables or a TOML config file loaded via
    :meth:`load`.

    Attributes:
        job_name_prefix: Prefix prepended to every created job's name.
        created_using_label: Value of the "created-using" label set on every job.
        owner_email_env_vars: Environment variables checked, in order, to
            determine the "created-by" label value. The default list covers the
            All of Us Researcher Workbench, which does not set ``$USER`` but does
            set ``$OWNER_EMAIL`` (and the equivalent ``$WORKBENCH_USER_EMAIL`` /
            ``$TERRA_USER_EMAIL``); without them every job there is labelled
            ``created-by=unknown``, which makes ``list-my-jobs`` useless.
        default_project_id: Fallback GCP project id when none is given on the
            command line or via ``$GOOGLE_PROJECT``.
        job_profiles: Named bundles of networking/VM settings selectable via
            ``--job-profile``. Always includes the built-in ``all-of-us`` profile;
            user-supplied profiles are merged with (and may override) it.
    """

    model_config = SettingsConfigDict(
        env_prefix="GC_BATCH_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Set by `load()` immediately before construction so `settings_customise_sources`
    # knows which config file (if any) to read. Not thread-safe: concurrent calls to
    # `load()` from different threads could race. This is acceptable for gc-batch's
    # CLI/script usage patterns; callers needing concurrency should pass `config_file`
    # explicitly and avoid overlapping `load()` calls.
    _config_file_override: ClassVar[Any] = _TOML_DISABLED

    job_name_prefix: str = ""
    created_using_label: str = "gc-batch"
    owner_email_env_vars: list[str] = Field(
        default_factory=lambda: [
            "OWNER_EMAIL",
            "WORKBENCH_USER_EMAIL",
            "TERRA_USER_EMAIL",
            "USER",
        ]
    )
    default_project_id: str | None = None
    job_profiles: dict[str, JobProfile] = Field(default_factory=dict)

    def __init__(self, **data: Any) -> None:
        """Initialize settings and merge in the built-in job profiles.

        Args:
            **data: Field overrides, following the standard pydantic-settings
                precedence (constructor arguments > environment variables >
                configured TOML source > defaults).
        """
        super().__init__(**data)
        self.job_profiles = {**_built_in_job_profiles(), **self.job_profiles}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Insert a TOML file source between env vars and the default sources.

        Returns:
            The settings sources in priority order (highest first): constructor
            arguments, environment variables, the TOML file (if one was
            requested via :meth:`load`), then the standard dotenv/secrets
            sources that fall through to field defaults.
        """
        sources: tuple[PydanticBaseSettingsSource, ...] = (
            init_settings,
            env_settings,
        )
        if cls._config_file_override is not _TOML_DISABLED:
            config_file = _resolve_config_file(cls._config_file_override)
            sources += (TomlConfigSettingsSource(settings_cls, toml_file=config_file),)
        return sources + (dotenv_settings, file_secret_settings)

    @classmethod
    def load(cls, config_file: str | Path | None = None, **overrides: Any) -> "GCBatchSettings":
        """Load settings, including values from a TOML configuration file.

        Args:
            config_file: An explicit path to a TOML config file. When omitted,
                the standard discovery order is used: ``$GC_BATCH_CONFIG_FILE``,
                then ``./gc-batch.toml``, then ``$XDG_CONFIG_HOME/gc-batch/config.toml``
                (or ``~/.config/gc-batch/config.toml`` when ``$XDG_CONFIG_HOME`` is unset).
            **overrides: Explicit field overrides, which take precedence over
                everything else (environment variables, the TOML file, and defaults).

        Returns:
            A fully resolved ``GCBatchSettings`` instance.
        """
        cls._config_file_override = config_file
        try:
            return cls(**overrides)
        finally:
            cls._config_file_override = _TOML_DISABLED
