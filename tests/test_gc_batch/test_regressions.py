"""Regression tests for latent crashes surfaced by mypy."""

from gc_batch.constants import EnvironmentVariables


class TestCreateEnvDictFromString:
    """create_env_dict_from_string is called on the class, so it must not take self."""

    def test_parses_single_pair(self):
        assert EnvironmentVariables.create_env_dict_from_string("KEY=value") == {"KEY": "value"}

    def test_parses_multiple_pairs(self):
        assert EnvironmentVariables.create_env_dict_from_string("A=1,B=2") == {"A": "1", "B": "2"}


def test_cli_exposes_version_option():
    """`gc-batch --version` must work.

    CONTRIBUTING.md and SECURITY.md both ask reporters for the gc-batch version,
    and the troubleshooting guide documents this flag, so the CLI has to provide it.
    """
    from click.testing import CliRunner

    from gc_batch.entrypoint import cli

    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0, result.output
    assert "gc-batch" in result.output
