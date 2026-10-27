"""Shared pytest fixtures."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_region_detection():
    """Keep CLI tests off the GCE metadata server and gcloud.

    Commands detect their region when --location is not passed; tests that care
    about detection patch ``gc_batch.entrypoint.get_current_region`` themselves.
    """
    with patch("gc_batch.entrypoint.get_current_region", return_value=None):
        yield
