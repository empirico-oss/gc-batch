from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from google.cloud.batch_v1.types import Job as GCSBatchJob
from google.cloud.batch_v1.types import JobStatus

from gc_batch.utils import get_formatted_start_and_end_time


@pytest.fixture
def mock_finished_job():
    """Create a mock finished job with create_time and update_time."""
    job = Mock(spec=GCSBatchJob)
    job.create_time = datetime(2024, 1, 1, 12, 0, 0)
    job.update_time = datetime(2024, 1, 1, 13, 30, 0)
    job.status = Mock()
    job.status.state = JobStatus.State.SUCCEEDED
    return job


@pytest.fixture
def mock_running_job():
    """Create a mock running job with create_time but no update_time."""
    job = Mock(spec=GCSBatchJob)
    job.create_time = datetime(2024, 1, 1, 12, 0, 0)
    job.update_time = None
    job.status = Mock()
    job.status.state = JobStatus.State.RUNNING
    return job


class TestGetFormattedStartAndEndTime:
    """Test cases for get_formatted_start_and_end_time function."""

    def test_finished_job_returns_both_times(self, mock_finished_job):
        """Test that a finished job returns both start and end times."""
        start_time, end_time = get_formatted_start_and_end_time(
            mock_finished_job, include_end_time_when_not_finished=False
        )

        assert start_time == "2024-01-01T12:00:00"
        assert end_time == "2024-01-01T13:30:00"

    def test_finished_job_with_include_end_time_flag(self, mock_finished_job):
        """Test that include_end_time_when_not_finished flag doesn't affect finished jobs."""
        start_time, end_time = get_formatted_start_and_end_time(
            mock_finished_job, include_end_time_when_not_finished=True
        )

        assert start_time == "2024-01-01T12:00:00"
        assert end_time == "2024-01-01T13:30:00"

    def test_running_job_without_flag_returns_none_end_time(self, mock_running_job):
        """Test that a running job without the flag returns None for end_time."""
        start_time, end_time = get_formatted_start_and_end_time(
            mock_running_job, include_end_time_when_not_finished=False
        )

        assert start_time == "2024-01-01T12:00:00"
        assert end_time is None

    def test_running_job_within_20_minutes_uses_start_plus_one_hour(self, mock_running_job):
        """Test that a running job started within 20 minutes uses start_time + 1 hour."""
        # Set create_time to 10 minutes ago (naive datetime will be converted to UTC-aware)
        # Use UTC time but remove timezone info to simulate a naive datetime representing UTC
        utc_time = datetime.now(timezone.utc)
        naive_time = utc_time.replace(tzinfo=None) - timedelta(minutes=10)
        mock_running_job.create_time = naive_time

        start_time, end_time = get_formatted_start_and_end_time(
            mock_running_job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # End time should be start_time + 1 hour
        # The function converts naive datetime to UTC-aware, so we need to account for that
        expected_end = (naive_time.replace(tzinfo=timezone.utc) + timedelta(hours=1)).isoformat()
        assert end_time == expected_end

    def test_running_job_exactly_20_minutes_uses_current_time(self, mock_running_job):
        """Test that a running job started exactly 20 minutes ago uses current time."""
        # Set create_time to exactly 20 minutes ago (edge case)
        mock_running_job.create_time = datetime.now() - timedelta(minutes=20)

        start_time, end_time = get_formatted_start_and_end_time(
            mock_running_job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        # At exactly 20 minutes, the condition current_time - start_time < 20 minutes is False
        # So end_time should be the formatted current time
        assert end_time is not None
        assert isinstance(end_time, str)
        # Verify it's a valid ISO format timestamp
        assert "T" in end_time

    def test_running_job_more_than_20_minutes_returns_current_time(self, mock_running_job):
        """Test that a running job started more than 20 minutes ago returns current time for end_time."""
        # Set create_time to 30 minutes ago
        mock_running_job.create_time = datetime.now() - timedelta(minutes=30)

        start_time, end_time = get_formatted_start_and_end_time(
            mock_running_job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        # When more than 20 minutes, end_time should be the formatted current time
        assert end_time is not None
        assert isinstance(end_time, str)
        # Verify it's a valid ISO format timestamp
        assert "T" in end_time

    def test_running_job_just_under_20_minutes_uses_start_plus_one_hour(self, mock_running_job):
        """Test that a running job started just under 20 minutes ago uses start_time + 1 hour."""
        # Set create_time to 19 minutes and 59 seconds ago (naive datetime will be converted to UTC-aware)
        # Use UTC time but remove timezone info to simulate a naive datetime representing UTC
        utc_time = datetime.now(timezone.utc)
        naive_time = utc_time.replace(tzinfo=None) - timedelta(minutes=19, seconds=59)
        mock_running_job.create_time = naive_time

        start_time, end_time = get_formatted_start_and_end_time(
            mock_running_job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # End time should be start_time + 1 hour
        # The function converts naive datetime to UTC-aware, so we need to account for that
        expected_end = (naive_time.replace(tzinfo=timezone.utc) + timedelta(hours=1)).isoformat()
        assert end_time == expected_end

    def test_failed_job_returns_both_times(self):
        """Test that a failed job returns both start and end times."""
        job = Mock(spec=GCSBatchJob)
        job.create_time = datetime(2024, 1, 1, 12, 0, 0)
        job.update_time = datetime(2024, 1, 1, 12, 15, 0)
        job.status = Mock()
        job.status.state = JobStatus.State.FAILED

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=False
        )

        assert start_time == "2024-01-01T12:00:00"
        assert end_time == "2024-01-01T12:15:00"

    def test_cancelled_job_returns_both_times(self):
        """Test that a cancelled job returns both start and end times."""
        job = Mock(spec=GCSBatchJob)
        job.create_time = datetime(2024, 1, 1, 12, 0, 0)
        job.update_time = datetime(2024, 1, 1, 12, 5, 0)
        job.status = Mock()
        job.status.state = JobStatus.State.CANCELLED

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=False
        )

        assert start_time == "2024-01-01T12:00:00"
        assert end_time == "2024-01-01T12:05:00"

    def test_job_with_microseconds_in_timestamp(self, mock_finished_job):
        """Test that timestamps with microseconds are formatted correctly."""
        mock_finished_job.create_time = datetime(2024, 1, 1, 12, 0, 0, 123456)
        mock_finished_job.update_time = datetime(2024, 1, 1, 13, 30, 0, 789012)

        start_time, end_time = get_formatted_start_and_end_time(
            mock_finished_job, include_end_time_when_not_finished=False
        )

        assert start_time == "2024-01-01T12:00:00.123456"
        assert end_time == "2024-01-01T13:30:00.789012"

    def test_job_with_timezone_aware_timestamp(self):
        """Test that timezone-aware timestamps are formatted correctly."""
        job = Mock(spec=GCSBatchJob)
        job.create_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job.update_time = datetime(2024, 1, 1, 13, 30, 0, tzinfo=timezone.utc)
        job.status = Mock()
        job.status.state = JobStatus.State.SUCCEEDED

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=False
        )

        # isoformat() will include timezone info
        assert "2024-01-01T12:00:00" in start_time
        assert "2024-01-01T13:30:00" in end_time
        assert (
            "+00:00" in start_time or "Z" in start_time or "+00:00" in end_time or "Z" in end_time
        )

    def test_running_job_timezone_aware_within_20_minutes(self):
        """Test that a running job with timezone-aware create_time within 20 minutes works correctly."""
        # This test covers the bug fix: timezone-aware datetimes from Google Cloud Batch
        job = Mock(spec=GCSBatchJob)
        # Set create_time to 10 minutes ago with UTC timezone (like Google Cloud Batch returns)
        job.create_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        job.update_time = None
        job.status = Mock()
        job.status.state = JobStatus.State.RUNNING

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # End time should be start_time + 1 hour (since it's within 20 minutes)
        expected_end = (job.create_time + timedelta(hours=1)).isoformat()
        assert end_time == expected_end

    def test_running_job_timezone_aware_more_than_20_minutes(self):
        """Test that a running job with timezone-aware create_time more than 20 minutes ago works correctly."""
        job = Mock(spec=GCSBatchJob)
        # Set create_time to 30 minutes ago with UTC timezone
        job.create_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        job.update_time = None
        job.status = Mock()
        job.status.state = JobStatus.State.RUNNING

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # End time should be the formatted current time (since it's more than 20 minutes)
        assert isinstance(end_time, str)
        assert "T" in end_time
        # Verify it includes timezone info (UTC)
        assert "+00:00" in end_time or "Z" in end_time

    def test_running_job_timezone_naive_converted_to_utc(self):
        """Test that a running job with timezone-naive create_time is converted to UTC."""
        job = Mock(spec=GCSBatchJob)
        # Set create_time to 10 minutes ago without timezone (naive datetime)
        # Create a naive datetime from UTC time to simulate Google Cloud Batch behavior
        # where timestamps are UTC but might be returned as naive
        utc_time = datetime.now(timezone.utc)
        naive_time = utc_time.replace(tzinfo=None) - timedelta(minutes=10)
        job.create_time = naive_time
        job.update_time = None
        job.status = Mock()
        job.status.state = JobStatus.State.RUNNING

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # End time should be start_time + 1 hour
        # The function should convert naive datetime to UTC-aware
        expected_end = (naive_time.replace(tzinfo=timezone.utc) + timedelta(hours=1)).isoformat()
        assert end_time == expected_end

    def test_running_job_timezone_aware_exactly_20_minutes(self):
        """Test edge case: running job with timezone-aware create_time exactly 20 minutes ago."""
        job = Mock(spec=GCSBatchJob)
        # Set create_time to exactly 20 minutes ago with UTC timezone
        job.create_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        job.update_time = None
        job.status = Mock()
        job.status.state = JobStatus.State.RUNNING

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # At exactly 20 minutes, condition is False, so end_time should be current time
        assert isinstance(end_time, str)
        assert "T" in end_time
        # Should include timezone info
        assert "+00:00" in end_time or "Z" in end_time

    def test_running_job_timezone_aware_just_under_20_minutes(self):
        """Test edge case: running job with timezone-aware create_time just under 20 minutes."""
        job = Mock(spec=GCSBatchJob)
        # Set create_time to 19 minutes 59 seconds ago with UTC timezone
        job.create_time = datetime.now(timezone.utc) - timedelta(minutes=19, seconds=59)
        job.update_time = None
        job.status = Mock()
        job.status.state = JobStatus.State.RUNNING

        start_time, end_time = get_formatted_start_and_end_time(
            job, include_end_time_when_not_finished=True
        )

        assert start_time is not None
        assert end_time is not None
        # Should use start_time + 1 hour since it's just under 20 minutes
        expected_end = (job.create_time + timedelta(hours=1)).isoformat()
        assert end_time == expected_end
