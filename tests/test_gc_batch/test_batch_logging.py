"""Unit tests for the BatchLogging class."""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from google.api_core.exceptions import PermissionDenied
from google.cloud import batch_v1
from google.cloud import logging as cloud_logging
from google.cloud.batch_v1.types import Job as GCSBatchJob
from google.cloud.batch_v1.types import JobStatus

from gc_batch.batch_logging import BatchLogging
from gc_batch.models.batch_config import BatchClientConfig


@pytest.fixture
def mock_config():
    """Create a mock BatchClientConfig."""
    config = Mock(spec=BatchClientConfig)
    config.project_id = "test-project"
    config.location = "us-central1"
    return config


@pytest.fixture
def mock_job():
    """Create a mock GCSBatchJob."""
    job = Mock(spec=GCSBatchJob)
    job.name = "projects/test-project/locations/us-central1/jobs/test-job-123"
    job.uid = "test-job-uid-123"
    job.create_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    job.update_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    job.status = Mock()
    job.status.state = JobStatus.State.SUCCEEDED
    job.labels = {}
    return job


@pytest.fixture
def mock_cloud_logging_client():
    """Create a mock Cloud Logging client."""
    return MagicMock()


@pytest.fixture
@patch("gc_batch.batch_logging.cloud_logging.Client")
@patch("gc_batch.batch_logging.get_logger")
def batch_logging_instance(mock_get_logger, mock_logging_client, mock_config):
    """Create a BatchLogging instance with mocked dependencies."""
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger

    instance = BatchLogging(mock_config)
    instance.cloud_logging_client = MagicMock()

    return instance


class TestBatchLoggingInit:
    """Test cases for BatchLogging initialization."""

    @patch("gc_batch.batch_logging.cloud_logging.Client")
    @patch("gc_batch.batch_logging.get_logger")
    def test_init_creates_clients(self, mock_get_logger, mock_logging_client, mock_config):
        """Test that initialization creates the necessary clients."""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        batch_logging = BatchLogging(mock_config)

        assert batch_logging.config == mock_config
        mock_get_logger.assert_called_once_with(name="BatchLogging", level=logging.INFO)
        mock_logging_client.assert_called_once_with(project=mock_config.project_id)


class TestCreateLogPolicy:
    """Test cases for create_log_policy method."""

    def test_create_log_policy_returns_correct_policy(self, batch_logging_instance):
        """Test that create_log_policy returns a LogsPolicy with CLOUD_LOGGING destination."""
        policy = batch_logging_instance.create_log_policy()

        assert isinstance(policy, batch_v1.LogsPolicy)
        assert policy.destination == batch_v1.LogsPolicy.Destination.CLOUD_LOGGING

    def test_create_log_policy_with_logs_path_uses_path_destination(self, batch_logging_instance):
        """Test that providing a logs_path returns a PATH destination policy."""
        policy = batch_logging_instance.create_log_policy(logs_path="/mnt/disks/logs/my-job")

        assert isinstance(policy, batch_v1.LogsPolicy)
        assert policy.destination == batch_v1.LogsPolicy.Destination.PATH
        assert policy.logs_path == "/mnt/disks/logs/my-job"

    def test_create_log_policy_with_empty_logs_path_uses_cloud_logging(
        self, batch_logging_instance
    ):
        """Test that an empty logs_path falls back to CLOUD_LOGGING."""
        policy = batch_logging_instance.create_log_policy(logs_path="")

        assert policy.destination == batch_v1.LogsPolicy.Destination.CLOUD_LOGGING


class TestGetTimeRangeFilters:
    """Test cases for get_time_range_filters classmethod."""

    @patch("gc_batch.batch_logging.get_formatted_start_and_end_time")
    def test_get_time_range_filters_with_both_times(self, mock_get_formatted_time):
        """Test that get_time_range_filters returns both start and end filters."""
        mock_job = Mock()
        mock_get_formatted_time.return_value = (
            "2024-01-01T12:00:00",
            "2024-01-01T13:00:00",
        )

        filters = BatchLogging.get_time_range_filters(mock_job)

        assert len(filters) == 2
        assert 'timestamp>="2024-01-01T12:00:00"' in filters
        assert 'timestamp<="2024-01-01T13:00:00"' in filters
        mock_get_formatted_time.assert_called_once_with(
            job=mock_job, include_end_time_when_not_finished=False
        )

    @patch("gc_batch.batch_logging.get_formatted_start_and_end_time")
    def test_get_time_range_filters_with_only_start_time(self, mock_get_formatted_time):
        """Test that get_time_range_filters returns only start filter when end is None."""
        mock_job = Mock()
        mock_get_formatted_time.return_value = ("2024-01-01T12:00:00", None)

        filters = BatchLogging.get_time_range_filters(mock_job)

        assert len(filters) == 1
        assert 'timestamp>="2024-01-01T12:00:00"' in filters

    @patch("gc_batch.batch_logging.get_formatted_start_and_end_time")
    def test_get_time_range_filters_with_no_times(self, mock_get_formatted_time):
        """Test that get_time_range_filters returns empty list when no times are available."""
        mock_job = Mock()
        mock_get_formatted_time.return_value = (None, None)

        filters = BatchLogging.get_time_range_filters(mock_job)

        assert len(filters) == 0


class TestGetFilterStringForJob:
    """Test cases for get_filter_string_for_job classmethod."""

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_filter_string_basic(self, mock_time_filters, mock_get_project_id):
        """Test that get_filter_string_for_job generates correct filter string with default params."""
        mock_job = Mock()
        mock_job.uid = "test-uid-123"
        mock_get_project_id.return_value = "test-project"
        mock_time_filters.return_value = []

        filter_str = BatchLogging.get_filter_string_for_job(mock_job, severity="DEFAULT")

        assert 'logName="projects/test-project/logs/batch_task_logs"' in filter_str
        assert 'logName="projects/test-project/logs/batch_agent_logs"' not in filter_str
        assert 'labels.job_uid="test-uid-123"' in filter_str
        assert "severity>=DEFAULT" in filter_str

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_filter_string_with_time_filters(self, mock_time_filters, mock_get_project_id):
        """Test that get_filter_string_for_job includes time range filters."""
        mock_job = Mock()
        mock_job.uid = "test-uid-123"
        mock_get_project_id.return_value = "test-project"
        mock_time_filters.return_value = [
            'timestamp>="2024-01-01T12:00:00"',
            'timestamp<="2024-01-01T13:00:00"',
        ]

        filter_str = BatchLogging.get_filter_string_for_job(mock_job, severity="INFO")

        assert 'timestamp>="2024-01-01T12:00:00"' in filter_str
        assert 'timestamp<="2024-01-01T13:00:00"' in filter_str
        assert "severity>=INFO" in filter_str

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_filter_string_without_severity(self, mock_time_filters, mock_get_project_id):
        """Test that get_filter_string_for_job handles empty severity."""
        mock_job = Mock()
        mock_job.uid = "test-uid-123"
        mock_get_project_id.return_value = "test-project"
        mock_time_filters.return_value = []

        filter_str = BatchLogging.get_filter_string_for_job(mock_job, severity="")

        assert 'labels.job_uid="test-uid-123"' in filter_str
        assert "severity>=" not in filter_str

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_filter_string_with_agent_logs(self, mock_time_filters, mock_get_project_id):
        """Test that get_filter_string_for_job uses batch_agent_logs when agent_logs=True."""
        mock_job = Mock()
        mock_job.uid = "test-uid-123"
        mock_get_project_id.return_value = "test-project"
        mock_time_filters.return_value = []

        filter_str = BatchLogging.get_filter_string_for_job(
            mock_job, severity="DEFAULT", agent_logs=True
        )

        assert 'logName="projects/test-project/logs/batch_agent_logs"' in filter_str
        assert 'logName="projects/test-project/logs/batch_task_logs"' not in filter_str
        assert 'labels.job_uid="test-uid-123"' in filter_str

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_filter_string_with_custom_label_filters(
        self, mock_time_filters, mock_get_project_id
    ):
        """Test that get_filter_string_for_job uses custom_label_filters when provided."""
        mock_job = Mock()
        mock_job.uid = "test-uid-123"
        mock_get_project_id.return_value = "test-project"
        mock_time_filters.return_value = []
        custom_filters = ['labels.custom_label="custom-value"', 'labels.another="test"']

        filter_str = BatchLogging.get_filter_string_for_job(
            mock_job, severity="INFO", custom_label_filters=custom_filters
        )

        # Should use custom filters instead of job_uid
        assert 'labels.custom_label="custom-value"' in filter_str
        assert 'labels.another="test"' in filter_str
        assert 'labels.job_uid="test-uid-123"' not in filter_str
        assert "severity>=INFO" in filter_str

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_filter_string_with_agent_logs_and_custom_filters(
        self, mock_time_filters, mock_get_project_id
    ):
        """Test combining agent_logs and custom_label_filters."""
        mock_job = Mock()
        mock_job.uid = "test-uid-123"
        mock_get_project_id.return_value = "test-project"
        mock_time_filters.return_value = []
        custom_filters = ['labels.run_id="run-123"']

        filter_str = BatchLogging.get_filter_string_for_job(
            mock_job,
            severity="ERROR",
            agent_logs=True,
            custom_label_filters=custom_filters,
        )

        assert 'logName="projects/test-project/logs/batch_agent_logs"' in filter_str
        assert 'labels.run_id="run-123"' in filter_str
        assert 'labels.job_uid="test-uid-123"' not in filter_str
        assert "severity>=ERROR" in filter_str


class TestGetCloudLoggingUrl:
    """Test cases for get_cloud_logging_url classmethod."""

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_generates_correct_url(
        self, mock_get_filter_string, mock_get_project_id
    ):
        """Test that get_cloud_logging_url generates the correct URL."""
        mock_job = Mock()
        mock_get_project_id.return_value = "test-project"
        mock_get_filter_string.return_value = 'labels.job_uid="test-uid"'

        url = BatchLogging.get_cloud_logging_url(mock_job, severity="DEFAULT")

        assert url.startswith("https://console.cloud.google.com/logs/query;query=")
        assert "?project=test-project" in url
        # Check that the filter string is URL-encoded
        assert "labels.job_uid" in url

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_encodes_filter(
        self, mock_get_filter_string, mock_get_project_id
    ):
        """Test that get_cloud_logging_url properly URL-encodes the filter string."""
        mock_job = Mock()
        mock_get_project_id.return_value = "test-project"
        # Filter with special characters that need encoding
        mock_get_filter_string.return_value = 'labels.job_uid="test uid with spaces"'

        url = BatchLogging.get_cloud_logging_url(mock_job, severity="INFO")

        # Verify the URL contains encoded characters (space becomes %20)
        assert "test%20uid%20with%20spaces" in url

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_with_agent_logs(
        self, mock_get_filter_string, mock_get_project_id
    ):
        """Test that get_cloud_logging_url passes agent_logs parameter."""
        mock_job = Mock()
        mock_get_project_id.return_value = "test-project"
        mock_get_filter_string.return_value = 'labels.job_uid="test-uid"'

        url = BatchLogging.get_cloud_logging_url(mock_job, severity="DEFAULT", agent_logs=True)

        # Verify get_filter_string_for_job was called with agent_logs=True
        mock_get_filter_string.assert_called_once()
        call_args = mock_get_filter_string.call_args
        assert call_args[0][0] == mock_job  # First positional arg is the job
        assert call_args[0][1] == "DEFAULT"  # Second positional arg is severity
        assert call_args[0][2] is True  # Third positional arg is agent_logs
        assert url.startswith("https://console.cloud.google.com/logs/query;query=")

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_with_run_id(self, mock_get_filter_string, mock_get_project_id):
        """Test that get_cloud_logging_url creates custom filters when custom_label_filters is provided."""
        mock_job = Mock()
        mock_job.labels = {"run_id": "run-123"}
        mock_get_project_id.return_value = "test-project"
        mock_get_filter_string.return_value = 'labels.run_id="run-123"'

        url = BatchLogging.get_cloud_logging_url(
            mock_job,
            severity="INFO",
            custom_label_filters={"run_id": "run-123"},
        )

        # Verify get_filter_string_for_job was called with custom_label_filters
        mock_get_filter_string.assert_called_once()
        call_args = mock_get_filter_string.call_args
        assert call_args[0][0] == mock_job
        assert call_args[0][1] == "INFO"
        assert call_args[0][2] is False  # agent_logs default
        # Check custom_label_filters contains run_id
        custom_filters = call_args[0][3]
        assert len(custom_filters) == 1
        assert 'labels.run_id="run-123"' in custom_filters[0]
        assert url.startswith("https://console.cloud.google.com/logs/query;query=")

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_with_agent_logs_and_run_id(
        self, mock_get_filter_string, mock_get_project_id
    ):
        """Test that get_cloud_logging_url combines agent_logs and custom_label_filters parameters."""
        mock_job = Mock()
        mock_job.labels = {"run_id": "run-456"}
        mock_get_project_id.return_value = "test-project"
        mock_get_filter_string.return_value = 'labels.run_id="run-456"'

        BatchLogging.get_cloud_logging_url(
            mock_job,
            severity="WARNING",
            agent_logs=True,
            custom_label_filters={"run_id": "run-456"},
        )

        # Verify both parameters were passed correctly
        mock_get_filter_string.assert_called_once()
        call_args = mock_get_filter_string.call_args
        assert call_args[0][0] == mock_job
        assert call_args[0][1] == "WARNING"
        assert call_args[0][2] is True  # agent_logs=True
        custom_filters = call_args[0][3]
        assert len(custom_filters) == 1
        assert 'labels.run_id="run-456"' in custom_filters[0]

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_without_run_id(
        self, mock_get_filter_string, mock_get_project_id
    ):
        """Test that get_cloud_logging_url uses job_uid filter when custom_label_filters is not provided."""
        mock_job = Mock()
        mock_job.labels = {}
        mock_job.uid = "test-uid"
        mock_get_project_id.return_value = "test-project"
        mock_get_filter_string.return_value = 'labels.job_uid="test-uid"'

        BatchLogging.get_cloud_logging_url(mock_job, severity="DEFAULT")

        # Verify get_filter_string_for_job was called with job_uid filter (not empty)
        mock_get_filter_string.assert_called_once()
        call_args = mock_get_filter_string.call_args
        custom_filters = call_args[0][3]
        assert len(custom_filters) == 1
        assert 'labels.job_uid="test-uid"' in custom_filters[0]

    @patch("gc_batch.batch_logging.GoogleUtils.get_project_id")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_get_cloud_logging_url_with_run_id_missing_label(
        self, mock_get_filter_string, mock_get_project_id
    ):
        """Test that get_cloud_logging_url uses job_uid filter when custom_label_filters is empty dict."""
        mock_job = Mock()
        mock_job.labels = {}  # No run_id label present
        mock_job.uid = "test-uid"
        mock_get_project_id.return_value = "test-project"
        mock_get_filter_string.return_value = 'labels.job_uid="test-uid"'

        BatchLogging.get_cloud_logging_url(mock_job, severity="DEFAULT", custom_label_filters={})

        # Verify get_filter_string_for_job was called with job_uid filter
        # since custom_label_filters was empty
        mock_get_filter_string.assert_called_once()
        call_args = mock_get_filter_string.call_args
        custom_filters = call_args[0][3]
        assert len(custom_filters) == 1
        assert 'labels.job_uid="test-uid"' in custom_filters[0]


class TestSortLogsChronologically:
    """Test cases for _sort_logs_chronologically method."""

    def test_sort_logs_chronologically_sorts_correctly(self, batch_logging_instance):
        """Test that logs are sorted in chronological order."""
        logs = [
            {"timestamp": "2024-01-01T13:00:00+00:00"},
            {"timestamp": "2024-01-01T11:00:00+00:00"},
            {"timestamp": "2024-01-01T12:00:00+00:00"},
        ]

        sorted_logs = batch_logging_instance._sort_logs_chronologically(logs)

        assert sorted_logs[0]["timestamp"] == "2024-01-01T11:00:00+00:00"
        assert sorted_logs[1]["timestamp"] == "2024-01-01T12:00:00+00:00"
        assert sorted_logs[2]["timestamp"] == "2024-01-01T13:00:00+00:00"

    def test_sort_logs_with_unknown_timestamps(self, batch_logging_instance):
        """Test that logs with unknown timestamps are placed at the beginning."""
        logs = [
            {"timestamp": "2024-01-01T12:00:00"},
            {"timestamp": "Unknown time"},
            {"timestamp": "2024-01-01T11:00:00"},
        ]

        sorted_logs = batch_logging_instance._sort_logs_chronologically(logs)

        # Unknown timestamps should be first, followed by chronologically sorted timestamps
        assert sorted_logs[0]["timestamp"] == "Unknown time"
        assert sorted_logs[1]["timestamp"] == "2024-01-01T11:00:00"
        assert sorted_logs[2]["timestamp"] == "2024-01-01T12:00:00"

    def test_sort_logs_with_mixed_timestamp_formats(self, batch_logging_instance):
        """Test that logs with only offset-aware timestamp formats are sorted correctly."""
        logs = [
            {"timestamp": "2024-01-01T13:00:00Z"},
            {"timestamp": "2024-01-01T11:00:00+00:00"},
            {"timestamp": "2024-01-01T12:00:00+00:00"},
        ]

        sorted_logs = batch_logging_instance._sort_logs_chronologically(logs)

        # All timestamps should be parsed and sorted correctly (oldest to newest)
        assert len(sorted_logs) == 3
        assert sorted_logs[0]["timestamp"] == "2024-01-01T11:00:00+00:00"
        assert sorted_logs[1]["timestamp"] == "2024-01-01T12:00:00+00:00"
        assert sorted_logs[2]["timestamp"] == "2024-01-01T13:00:00Z"


class TestQueryCloudLogs:
    """Test cases for _query_cloud_logs method."""

    def test_query_cloud_logs_returns_log_entries(self, batch_logging_instance):
        """Test that _query_cloud_logs returns formatted log entries."""
        mock_entry1 = Mock()
        mock_entry1.timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_entry1.severity.name = "INFO"
        mock_entry1.payload = {"textPayload": "Test log message"}
        mock_entry1.resource.type = "gce_instance"
        mock_entry1.resource.labels = {"instance_id": "123"}

        mock_entry2 = Mock()
        mock_entry2.timestamp = datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
        mock_entry2.severity.name = "ERROR"
        mock_entry2.payload = {"textPayload": "Error message"}
        mock_entry2.resource.type = "gce_instance"
        mock_entry2.resource.labels = {"instance_id": "123"}

        batch_logging_instance.cloud_logging_client.list_entries.return_value = [
            mock_entry1,
            mock_entry2,
        ]

        logs = batch_logging_instance._query_cloud_logs("test filter", max_results=10)

        assert len(logs) == 2
        assert logs[0]["severity"] == "INFO"
        assert logs[0]["textPayload"] == "Test log message"
        assert logs[1]["severity"] == "ERROR"
        assert logs[1]["textPayload"] == "Error message"

    def test_query_cloud_logs_calls_client_with_correct_params(self, batch_logging_instance):
        """Test that _query_cloud_logs calls the client with correct parameters."""
        batch_logging_instance.cloud_logging_client.list_entries.return_value = []

        batch_logging_instance._query_cloud_logs("test filter", max_results=100)

        batch_logging_instance.cloud_logging_client.list_entries.assert_called_once_with(
            filter_="test filter",
            max_results=100,
            order_by=cloud_logging.DESCENDING,
        )

    def test_query_cloud_logs_propagates_api_error(self, batch_logging_instance):
        """A failed Cloud Logging query must not be reported as an empty result."""
        batch_logging_instance.cloud_logging_client.list_entries.side_effect = PermissionDenied(
            "Permission denied for all log views"
        )

        with pytest.raises(PermissionDenied):
            batch_logging_instance._query_cloud_logs("test filter")

        batch_logging_instance.logging.error.assert_called_once()

    def test_query_cloud_logs_handles_severity_without_name_attribute(self, batch_logging_instance):
        """Test that _query_cloud_logs handles severity objects without name attribute."""
        mock_entry = Mock()
        mock_entry.timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Create a mock severity that will be converted to string
        # Use a simple string value instead of a complex object
        mock_entry.severity = "WARNING"

        mock_entry.payload = {"textPayload": "Test message"}
        mock_entry.resource.type = "gce_instance"
        mock_entry.resource.labels = {}

        batch_logging_instance.cloud_logging_client.list_entries.return_value = [mock_entry]

        logs = batch_logging_instance._query_cloud_logs("test filter")

        assert len(logs) == 1
        # Should convert the severity to string since it doesn't have a name attribute
        assert logs[0]["severity"] == "WARNING"


class TestPrintLogsForJob:
    """Test cases for print_logs_for_job method."""

    @patch("builtins.print")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_print_logs_for_job_displays_logs(
        self, mock_get_filter_string, mock_print, batch_logging_instance, mock_job
    ):
        """Test that print_logs_for_job displays logs to console."""
        mock_get_filter_string.return_value = "test filter"

        mock_logs = [
            {
                "timestamp": "2024-01-01T12:00:00",
                "severity": "INFO",
                "textPayload": "Log message 1",
            },
            {
                "timestamp": "2024-01-01T12:01:00",
                "severity": "ERROR",
                "textPayload": "Log message 2",
            },
        ]

        batch_logging_instance._query_cloud_logs = Mock(return_value=mock_logs)
        batch_logging_instance._sort_logs_chronologically = Mock(return_value=mock_logs)

        batch_logging_instance.print_logs_for_job(mock_job, severity="DEFAULT")

        # Check that print was called (multiple times for formatting and log entries)
        assert mock_print.call_count > 0

    @patch("builtins.print")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_print_logs_for_job_handles_no_logs(
        self, mock_get_filter_string, mock_print, batch_logging_instance, mock_job
    ):
        """Test that print_logs_for_job handles case with no logs found."""
        mock_get_filter_string.return_value = "test filter"
        batch_logging_instance._query_cloud_logs = Mock(return_value=[])

        batch_logging_instance.print_logs_for_job(mock_job, severity="DEFAULT")

        batch_logging_instance.logging.warning.assert_called_once()
        # An empty-but-successful query must read as "nothing matched", not as an error.
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "No log entries matched" in printed

    @patch("builtins.print")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_print_logs_for_job_propagates_failure_without_claiming_no_logs(
        self, mock_get_filter_string, mock_print, batch_logging_instance, mock_job
    ):
        """A query failure must surface as an error, not as "no logs found"."""
        mock_get_filter_string.return_value = "test filter"
        batch_logging_instance._query_cloud_logs = Mock(
            side_effect=PermissionDenied("Permission denied for all log views")
        )

        with pytest.raises(PermissionDenied):
            batch_logging_instance.print_logs_for_job(mock_job, severity="DEFAULT")

        # Reported once, by the caller that catches it — not a second time here.
        batch_logging_instance.logging.error.assert_not_called()
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "No log" not in printed

    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_print_logs_for_job_returns_entry_count(
        self, mock_get_filter_string, batch_logging_instance, mock_job
    ):
        """The caller needs the entry count to tell empty from failed."""
        mock_get_filter_string.return_value = "test filter"
        batch_logging_instance._query_cloud_logs = Mock(
            return_value=[{"timestamp": "t", "severity": "INFO", "textPayload": "m"}]
        )

        assert batch_logging_instance.print_logs_for_job(mock_job) == 1


class TestDownloadLogsForJob:
    """Test cases for download_logs_for_job method."""

    @patch("gc_batch.batch_logging.GoogleUtils.get_job_name")
    @patch("gc_batch.batch_logging.os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_download_logs_for_job_creates_file(
        self,
        mock_get_filter_string,
        mock_file,
        mock_makedirs,
        mock_get_job_name,
        batch_logging_instance,
        mock_job,
    ):
        """Test that download_logs_for_job creates a log file."""
        mock_get_filter_string.return_value = "test filter"
        mock_get_job_name.return_value = "test-job-123"

        mock_logs = [
            {
                "timestamp": "2024-01-01T12:00:00",
                "severity": "INFO",
                "textPayload": "Log message 1",
            },
        ]

        batch_logging_instance._query_cloud_logs = Mock(return_value=mock_logs)
        batch_logging_instance._sort_logs_chronologically = Mock(return_value=mock_logs)

        batch_logging_instance.download_logs_for_job(mock_job, "/tmp/logs", severity="DEFAULT")

        mock_makedirs.assert_called_once_with("/tmp/logs", exist_ok=True)
        mock_file.assert_called_once_with("/tmp/logs/test-job-123.log", "w")

        # Check that log content was written
        handle = mock_file()
        handle.write.assert_called()

    @patch("gc_batch.batch_logging.os.makedirs")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_download_logs_for_job_handles_no_logs(
        self,
        mock_get_filter_string,
        mock_makedirs,
        batch_logging_instance,
        mock_job,
    ):
        """Test that download_logs_for_job handles case with no logs found."""
        mock_get_filter_string.return_value = "test filter"
        batch_logging_instance._query_cloud_logs = Mock(return_value=[])

        assert batch_logging_instance.download_logs_for_job(mock_job, "/tmp/logs") == 0

        batch_logging_instance.logging.warning.assert_called_once()
        assert "No log entries matched" in str(batch_logging_instance.logging.warning.call_args)

    @patch("gc_batch.batch_logging.os.makedirs")
    @patch("gc_batch.batch_logging.BatchLogging.get_filter_string_for_job")
    def test_download_logs_for_job_propagates_failure(
        self,
        mock_get_filter_string,
        mock_makedirs,
        batch_logging_instance,
        mock_job,
    ):
        """A query failure must surface as an error rather than being swallowed."""
        mock_get_filter_string.return_value = "test filter"
        batch_logging_instance._query_cloud_logs = Mock(
            side_effect=PermissionDenied("Permission denied for all log views")
        )

        with pytest.raises(PermissionDenied):
            batch_logging_instance.download_logs_for_job(mock_job, "/tmp/logs")

        # Reported once, by the caller that catches it — not a second time here.
        batch_logging_instance.logging.error.assert_not_called()


class TestGetInstanceIdFromLogs:
    """Test cases for get_instance_id_from_logs method."""

    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_instance_id_from_logs_returns_instance_id(
        self, mock_time_filters, batch_logging_instance, mock_job
    ):
        """Test that get_instance_id_from_logs returns the first instance ID found."""
        mock_time_filters.return_value = []

        mock_logs = [
            {
                "resource": {
                    "type": "gce_instance",
                    "labels": {"instance_id": "123456789"},
                }
            }
        ]

        batch_logging_instance._query_cloud_logs = Mock(return_value=mock_logs)

        instance_id = batch_logging_instance.get_instance_id_from_logs(mock_job)

        assert instance_id == "123456789"

    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_instance_id_from_logs_returns_none_when_not_found(
        self, mock_time_filters, batch_logging_instance, mock_job
    ):
        """Test that get_instance_id_from_logs returns None when no instance ID is found."""
        mock_time_filters.return_value = []

        mock_logs = [{"resource": {"type": "gce_instance", "labels": {}}}]

        batch_logging_instance._query_cloud_logs = Mock(return_value=mock_logs)

        instance_id = batch_logging_instance.get_instance_id_from_logs(mock_job)

        assert instance_id is None

    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_instance_id_from_logs_handles_empty_logs(
        self, mock_time_filters, batch_logging_instance, mock_job
    ):
        """Test that get_instance_id_from_logs handles empty log results."""
        mock_time_filters.return_value = []
        batch_logging_instance._query_cloud_logs = Mock(return_value=[])

        instance_id = batch_logging_instance.get_instance_id_from_logs(mock_job)

        assert instance_id is None

    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_instance_id_from_logs_returns_none_when_query_fails(
        self, mock_time_filters, batch_logging_instance, mock_job
    ):
        """This caller legitimately tolerates failure and must keep returning None."""
        mock_time_filters.return_value = []
        batch_logging_instance._query_cloud_logs = Mock(
            side_effect=PermissionDenied("Permission denied for all log views")
        )

        assert batch_logging_instance.get_instance_id_from_logs(mock_job) is None

    @patch("gc_batch.batch_logging.BatchLogging.get_time_range_filters")
    def test_get_instance_id_from_logs_uses_time_filters(
        self, mock_time_filters, batch_logging_instance, mock_job
    ):
        """Test that get_instance_id_from_logs includes time range filters in query."""
        mock_time_filters.return_value = ['timestamp>="2024-01-01T12:00:00"']
        batch_logging_instance._query_cloud_logs = Mock(return_value=[])

        batch_logging_instance.get_instance_id_from_logs(mock_job)

        # Verify the filter string includes time filters
        call_args = batch_logging_instance._query_cloud_logs.call_args[0][0]
        assert 'timestamp>="2024-01-01T12:00:00"' in call_args


class TestDownloadLogsForJobWithTimeRange:
    """Test cases for download_logs_for_job_with_time_range method."""

    def test_download_logs_for_job_with_time_range_calls_download_logs(
        self, batch_logging_instance, mock_job
    ):
        """Test that download_logs_for_job_with_time_range delegates to download_logs_for_job."""
        batch_logging_instance.download_logs_for_job = Mock()

        batch_logging_instance.download_logs_for_job_with_time_range(
            mock_job, "/tmp/logs", severity="INFO"
        )

        batch_logging_instance.download_logs_for_job.assert_called_once_with(
            mock_job, "/tmp/logs", "INFO"
        )


class TestPrintLogsForJobWithTimeRange:
    """Test cases for print_logs_for_job_with_time_range method."""

    def test_print_logs_for_job_with_time_range_calls_print_logs(
        self, batch_logging_instance, mock_job
    ):
        """Test that print_logs_for_job_with_time_range delegates to print_logs_for_job."""
        batch_logging_instance.print_logs_for_job = Mock()

        batch_logging_instance.print_logs_for_job_with_time_range(mock_job, severity="WARNING")

        batch_logging_instance.print_logs_for_job.assert_called_once_with(mock_job, "WARNING")
