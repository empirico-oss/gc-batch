"""Unit tests for the GCSLogReader class.

All GCS access is faked; these tests never touch the network.
"""

from __future__ import annotations

import pytest
from google.cloud import batch_v1
from google.cloud.batch_v1.types import Job as GCSBatchJob

from gc_batch.constants import Constants
from gc_batch.gcs_logging import GCSLogReader
from gc_batch.models.batch_config import BatchClientConfig

JOB_UID = "j-abc123"
BUCKET = "logs-bucket"
PREFIX = "batch-logs/my-job-1"


class FakeBlob:
    """Minimal stand-in for ``google.cloud.storage.Blob``."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self.size = len(data)
        self._data = data

    def download_as_bytes(self) -> bytes:
        return self._data


class FakeBucket:
    """Minimal stand-in for ``google.cloud.storage.Bucket``."""

    def __init__(self, name: str, blobs: list[FakeBlob], user_project: str | None):
        self.name = name
        self.user_project = user_project
        self._blobs = blobs
        self.list_blobs_prefixes: list[str | None] = []

    def list_blobs(self, prefix: str | None = None) -> list[FakeBlob]:
        self.list_blobs_prefixes.append(prefix)
        if prefix is None:
            return list(self._blobs)
        return [blob for blob in self._blobs if blob.name.startswith(prefix)]


class FakeStorageClient:
    """Minimal stand-in for ``google.cloud.storage.Client``."""

    def __init__(self, blobs: dict[str, bytes] | None = None):
        self._blobs = [FakeBlob(name, data) for name, data in (blobs or {}).items()]
        self.requested_buckets: list[tuple[str, str | None]] = []

    def bucket(self, bucket_name: str, user_project: str | None = None) -> FakeBucket:
        self.requested_buckets.append((bucket_name, user_project))
        return FakeBucket(bucket_name, self._blobs, user_project)


def _object_name(stream: str, task: int = 0, group: int = 0) -> str:
    return f"{PREFIX}/{stream}-{JOB_UID}-group{group}-{task}.log"


def _make_path_job(
    remote_path: str = f"{BUCKET}/{PREFIX}",
    mount_options: list[str] | None = None,
) -> GCSBatchJob:
    """Build a Batch job whose logs are routed to a mounted GCS bucket."""
    volume = batch_v1.Volume(
        gcs=batch_v1.GCS(remote_path=remote_path),
        mount_path=Constants.LOGS_MOUNT_POINT,
        mount_options=mount_options or ["--implicit-dirs"],
    )
    return batch_v1.Job(
        name="projects/test-project/locations/us-central1/jobs/my-job-1",
        uid=JOB_UID,
        task_groups=[batch_v1.TaskGroup(task_spec=batch_v1.TaskSpec(volumes=[volume]))],
        logs_policy=batch_v1.LogsPolicy(
            destination=batch_v1.LogsPolicy.Destination.PATH,
            logs_path=f"{Constants.LOGS_MOUNT_POINT}/",
        ),
    )


def _make_cloud_logging_job() -> GCSBatchJob:
    """Build a Batch job that writes to Cloud Logging (no logs volume)."""
    volume = batch_v1.Volume(
        gcs=batch_v1.GCS(remote_path="data-bucket/input"),
        mount_path=Constants.INPUT_MOUNT_POINT,
    )
    return batch_v1.Job(
        name="projects/test-project/locations/us-central1/jobs/cloud-job-1",
        uid=JOB_UID,
        task_groups=[batch_v1.TaskGroup(task_spec=batch_v1.TaskSpec(volumes=[volume]))],
        logs_policy=batch_v1.LogsPolicy(destination=batch_v1.LogsPolicy.Destination.CLOUD_LOGGING),
    )


def _make_reader(blobs: dict[str, bytes] | None = None) -> GCSLogReader:
    config = BatchClientConfig(project_id="test-project", location="us-central1")
    return GCSLogReader(config=config, storage_client=FakeStorageClient(blobs))


def _task_line(message: str, timestamp: str = "2026/09/18 16:11:40", severity: str = "INFO") -> str:
    return (
        f"[batch_task_logs]{timestamp} {severity}: "
        f"[task_id:task/{JOB_UID}-group0-0/0/0,runnable_index:0] {message}"
    )


class TestResolveLogLocation:
    def test_resolves_bucket_and_prefix_from_logs_volume(self):
        location = GCSLogReader.resolve_log_location(_make_path_job())

        assert location.bucket == BUCKET
        assert location.prefix == PREFIX

    def test_bucket_only_remote_path_has_empty_prefix(self):
        location = GCSLogReader.resolve_log_location(_make_path_job(remote_path=BUCKET))

        assert location.bucket == BUCKET
        assert location.prefix == ""

    def test_reads_billing_project_from_mount_options(self):
        job = _make_path_job(mount_options=["--billing-project=pays-for-it", "--implicit-dirs"])

        assert GCSLogReader.resolve_log_location(job).billing_project == "pays-for-it"

    def test_no_billing_project_when_not_requester_pays(self):
        assert GCSLogReader.resolve_log_location(_make_path_job()).billing_project is None

    def test_cloud_logging_job_raises_naming_job_and_destination(self):
        with pytest.raises(ValueError) as excinfo:
            GCSLogReader.resolve_log_location(_make_cloud_logging_job())

        message = str(excinfo.value)
        assert "cloud-job-1" in message
        assert "CLOUD_LOGGING" in message

    def test_uses_gcs_logs_distinguishes_destinations(self):
        assert GCSLogReader.uses_gcs_logs(_make_path_job()) is True
        assert GCSLogReader.uses_gcs_logs(_make_cloud_logging_job()) is False


class TestListLogObjects:
    def test_lists_only_objects_under_the_job_prefix(self):
        reader = _make_reader(
            {
                _object_name("stdout"): b"",
                _object_name("stderr"): b"",
                "batch-logs/other-job-9/stdout-other-group0-0.log": b"",
            }
        )

        names = reader.list_log_objects(_make_path_job())

        assert names == [_object_name("stderr"), _object_name("stdout")]

    def test_has_log_objects_false_when_batch_wrote_nothing(self):
        assert _make_reader({}).has_log_objects(_make_path_job()) is False

    def test_has_log_objects_true_when_objects_exist(self):
        reader = _make_reader({_object_name("stdout"): b""})

        assert reader.has_log_objects(_make_path_job()) is True

    def test_passes_billing_project_as_user_project(self):
        reader = _make_reader({})
        job = _make_path_job(mount_options=["--billing-project=pays-for-it"])

        reader.list_log_objects(job)

        storage_client = reader.storage_client
        assert storage_client.requested_buckets == [(BUCKET, "pays-for-it")]  # type: ignore[attr-defined]


class TestReadLogsForJob:
    def test_parses_task_line_into_entry(self):
        reader = _make_reader({_object_name("stdout"): _task_line("hello").encode()})

        entries = reader.read_logs_for_job(_make_path_job())

        assert len(entries) == 1
        assert entries[0]["timestamp"] == "2026-09-18T16:11:40+00:00"
        assert entries[0]["severity"] == "INFO"
        assert entries[0]["textPayload"] == "hello"

    def test_strips_task_id_prefix_into_resource_labels(self):
        reader = _make_reader({_object_name("stdout"): _task_line("hello").encode()})

        entry = reader.read_logs_for_job(_make_path_job())[0]

        assert "task_id" not in entry["textPayload"]
        labels = entry["resource"]["labels"]
        assert labels["task_id"] == f"task/{JOB_UID}-group0-0/0/0"
        assert labels["runnable_index"] == "0"
        assert labels["stream_tag"] == "batch_task_logs"
        assert labels["stream"] == "stdout"

    def test_stderr_lines_keep_error_severity(self):
        reader = _make_reader(
            {
                _object_name("stderr"): (
                    "[batch_task_logs]2026/09/18 16:11:40 ERROR: "
                    f"[task_id:task/{JOB_UID}-group0-0/0/0,runnable_index:0] boom"
                ).encode()
            }
        )

        entries = reader.read_logs_for_job(_make_path_job())

        assert [(e["severity"], e["textPayload"]) for e in entries] == [("ERROR", "boom")]

    def test_agent_lines_excluded_by_default(self):
        reader = _make_reader(
            {
                _object_name("stdout"): _task_line("task output").encode(),
                _object_name("output"): (
                    "[batch_agent_logs]2026/09/18 16:11:39 INFO: docker run --rm image\n"
                    + _task_line("task output")
                ).encode(),
            }
        )

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["task output"]

    def test_agent_lines_included_on_request(self):
        reader = _make_reader(
            {
                _object_name("stdout"): _task_line("task output").encode(),
                _object_name("output"): (
                    "[batch_agent_logs]2026/09/18 16:11:39 INFO: docker run --rm image\n"
                    + _task_line("task output")
                ).encode(),
            }
        )

        entries = reader.read_logs_for_job(_make_path_job(), include_agent_logs=True)

        # The `output-` object is the superset, so it replaces stdout/stderr rather
        # than duplicating their lines.
        assert [e["textPayload"] for e in entries] == ["docker run --rm image", "task output"]
        assert entries[0]["resource"]["labels"]["stream_tag"] == "batch_agent_logs"

    def test_unprefixed_lines_continue_the_previous_message(self):
        payload = (_task_line("first line") + "\ncontinued\nstill continued").encode()
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job())

        assert len(entries) == 1
        assert entries[0]["textPayload"] == "first line\ncontinued\nstill continued"

    def test_leading_unprefixed_line_is_preserved_as_its_own_entry(self):
        reader = _make_reader({_object_name("stdout"): b"orphan line"})

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["orphan line"]

    def test_decodes_invalid_utf8_lossily(self):
        payload = _task_line("bad ").encode() + b"\xc3"
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job())

        assert entries[0]["textPayload"] == "bad �"

    def test_preserves_file_order_for_same_second_lines(self):
        lines = [_task_line(f"line-{index}") for index in range(50)]
        reader = _make_reader({_object_name("stdout"): "\n".join(lines).encode()})

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == [f"line-{index}" for index in range(50)]

    def test_does_not_reorder_out_of_order_timestamps(self):
        payload = "\n".join(
            [
                _task_line("later", timestamp="2026/09/18 16:11:45"),
                _task_line("earlier", timestamp="2026/09/18 16:11:40"),
            ]
        ).encode()
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["later", "earlier"]

    def test_very_long_single_line_survives_intact(self):
        long_message = "x" * 100_000
        reader = _make_reader({_object_name("stdout"): _task_line(long_message).encode()})

        entries = reader.read_logs_for_job(_make_path_job())

        assert len(entries) == 1
        assert entries[0]["textPayload"] == long_message

    def test_strips_trailing_carriage_returns(self):
        payload = (_task_line("windows line") + "\r\n" + _task_line("second")).encode()
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["windows line", "second"]

    def test_empty_stderr_object_contributes_nothing(self):
        reader = _make_reader(
            {
                _object_name("stdout"): _task_line("only stdout").encode(),
                _object_name("stderr"): b"",
            }
        )

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["only stdout"]

    def test_enumerates_every_task_in_order(self):
        reader = _make_reader(
            {
                _object_name("stdout", task=1): _task_line("task one").encode(),
                _object_name("stdout", task=0): _task_line("task zero").encode(),
                _object_name("stderr", task=0): _task_line("task zero err").encode(),
            }
        )

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["task zero", "task zero err", "task one"]

    def test_ignores_objects_that_are_not_batch_log_files(self):
        reader = _make_reader(
            {
                f"{PREFIX}/": b"",
                f"{PREFIX}/notes.txt": b"not a log",
                _object_name("stdout"): _task_line("real log").encode(),
            }
        )

        entries = reader.read_logs_for_job(_make_path_job())

        assert [e["textPayload"] for e in entries] == ["real log"]

    def test_returns_empty_list_when_no_objects_exist(self):
        assert _make_reader({}).read_logs_for_job(_make_path_job()) == []


class TestSeverityFiltering:
    def test_threshold_keeps_only_equal_or_higher_severities(self):
        payload = "\n".join(
            [
                _task_line("debug line", severity="DEBUG"),
                _task_line("info line", severity="INFO"),
                _task_line("error line", severity="ERROR"),
            ]
        ).encode()
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job(), severity="INFO")

        assert [e["textPayload"] for e in entries] == ["info line", "error line"]

    def test_default_threshold_keeps_everything(self):
        payload = "\n".join(
            [
                _task_line("debug line", severity="DEBUG"),
                _task_line("error line", severity="ERROR"),
            ]
        ).encode()
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job(), severity="DEFAULT")

        assert len(entries) == 2

    def test_notice_ranks_between_info_and_warning(self):
        payload = "\n".join(
            [
                _task_line("info line", severity="INFO"),
                _task_line("notice line", severity="NOTICE"),
                _task_line("warning line", severity="WARNING"),
            ]
        ).encode()
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job(), severity="NOTICE")

        assert [e["textPayload"] for e in entries] == ["notice line", "warning line"]

    def test_unknown_requested_severity_raises(self):
        reader = _make_reader({_object_name("stdout"): _task_line("hello").encode()})

        with pytest.raises(ValueError) as excinfo:
            reader.read_logs_for_job(_make_path_job(), severity="BOGUS")

        assert "BOGUS" in str(excinfo.value)

    def test_severity_comparison_is_case_insensitive(self):
        reader = _make_reader({_object_name("stdout"): _task_line("hello").encode()})

        assert len(reader.read_logs_for_job(_make_path_job(), severity="info")) == 1

    def test_unknown_line_severity_is_preserved_and_not_dropped(self):
        payload = b"[batch_task_logs]2026/09/18 16:11:40 WEIRD: hello"
        reader = _make_reader({_object_name("stdout"): payload})

        entries = reader.read_logs_for_job(_make_path_job())

        assert entries[0]["severity"] == "WEIRD"
        assert entries[0]["textPayload"] == "hello"


class TestStderrIsInterleavedInEmissionOrder:
    """stderr must appear where it was emitted, not after all stdout.

    Reading the ``stdout-`` and ``stderr-`` objects in sequence put every stderr
    line after every stdout line, so a job that wrote to stderr mid-run had its
    output reordered. Batch timestamps have one-second resolution, so the true
    order cannot be recovered afterwards — it has to come from the ``output-``
    object, which Batch writes in emission order.
    """

    def _job_with_interleaved_streams(self) -> dict[str, bytes]:
        output = "\n".join(
            [
                "[batch_agent_logs]2026/09/18 16:11:35 INFO: Runnable command line: docker run …",
                _task_line("first"),
                _task_line("on stderr", severity="ERROR"),
                _task_line("DONE"),
                "[batch_agent_logs]2026/09/18 16:11:40 INFO: Task succeeded",
            ]
        )
        return {
            f"{PREFIX}/output-{JOB_UID}-group0-0.log": output.encode(),
            f"{PREFIX}/stdout-{JOB_UID}-group0-0.log": (
                _task_line("first") + "\n" + _task_line("DONE")
            ).encode(),
            f"{PREFIX}/stderr-{JOB_UID}-group0-0.log": _task_line(
                "on stderr", severity="ERROR"
            ).encode(),
        }

    def test_stderr_keeps_its_position_between_stdout_lines(self):
        reader = _make_reader(self._job_with_interleaved_streams())

        messages = [e["textPayload"] for e in reader.read_logs_for_job(_make_path_job())]

        assert messages == ["first", "on stderr", "DONE"]

    def test_agent_lines_are_excluded_by_default(self):
        reader = _make_reader(self._job_with_interleaved_streams())

        messages = [e["textPayload"] for e in reader.read_logs_for_job(_make_path_job())]

        assert not any("docker run" in m for m in messages)
        assert not any("Task succeeded" in m for m in messages)

    def test_agent_lines_are_included_on_request(self):
        reader = _make_reader(self._job_with_interleaved_streams())

        messages = [
            e["textPayload"]
            for e in reader.read_logs_for_job(_make_path_job(), include_agent_logs=True)
        ]

        assert any("docker run" in m for m in messages)
        assert messages.index("on stderr") < messages.index("DONE")

    def test_falls_back_to_the_stream_pair_when_no_output_object_exists(self):
        blobs = self._job_with_interleaved_streams()
        del blobs[f"{PREFIX}/output-{JOB_UID}-group0-0.log"]
        reader = _make_reader(blobs)

        messages = [e["textPayload"] for e in reader.read_logs_for_job(_make_path_job())]

        assert sorted(messages) == ["DONE", "first", "on stderr"]
