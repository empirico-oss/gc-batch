# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0]

First public release.

### Added

- CLI for managing Google Cloud Batch jobs: `create`, `list-jobs`, `list-my-jobs`,
  `status`, `logs`, `cancel`, and `show-config`.
- `gc-batch --version`, which the contributing and security guides ask bug
  reporters to include.
- `GCBatchClient`, a Python client for the same operations, and
  `BatchJobConfig.apply_profile`, which applies a `JobProfile`'s networking and VM
  settings to a job config — what `create --job-profile` does under the hood, also
  reachable directly from library code.
- GCS bucket mounts for job input, output, and logs, and local SSD storage.
- Automatic `job-name`, `created-using`, `created-at`, and `created-by` labels, plus
  filtering by label, name, status, and time window. The `created-by` label is set
  by `GCBatchClient.create_job`, so jobs submitted through the Python client carry
  it too and are found by `list-my-jobs`; a `created-by` passed in
  `JobRequest.labels` takes precedence over the environment-derived value.
  `owner_email_env_vars` defaults to
  `["OWNER_EMAIL", "WORKBENCH_USER_EMAIL", "TERRA_USER_EMAIL", "USER"]`, so
  `created-by` (and therefore `list-my-jobs`) works inside the All of Us Researcher
  Workbench, which sets the first three but not `$USER`; `$USER` remains the final
  fallback elsewhere.
- `GCBatchSettings` (`gc_batch.settings`), resolving configuration from constructor
  arguments, `GC_BATCH_*` environment variables, a TOML config file, and neutral
  defaults, in that precedence order.
- Named job profiles via `--job-profile`, including a built-in `all-of-us` profile
  for the restricted-VPC All of Us Researcher Workbench environment. `create` warns
  when a job profile declares that Cloud Logging is unreadable and no
  `--logs-bucket` was given — the case where a job's logs are written somewhere the
  user cannot read them. The log destination is fixed when the job is created, so
  the warning names the only remedy: recreate with `--logs-bucket`. The `all-of-us`
  profile sets this `cloud_logging_unreadable` flag; it defaults to false, so
  nothing changes for other profiles. The warning goes to stderr and does not block
  job creation, and the `Cloud Logging URL` line that `create` prints on success is
  annotated in the same case, since that URL will show nothing.
- Logs written to a GCS bucket are readable. `gc-batch logs print` and
  `logs download` detect that a job was created with `--logs-bucket` and read the
  log objects out of the bucket instead of querying Cloud Logging. That is the only
  working log route where the caller has no Cloud Logging read access at all — for
  example the All of Us Researcher Workbench, where the workspace pet service
  account gets `403 Permission denied for all log views`. The bucket and per-job
  prefix are recovered from the job resource, so nothing extra has to be passed.
  Logs written with `--logs-bucket` land in a per-job subfolder beneath the given
  path, `gs://<logs-bucket-path>/<generated-job-name>/`; the path printed by
  `create` is the parent folder, not the one holding that job's files.
- `GCSLogReader` (`gc_batch.gcs_logging`) for reading those logs from Python. It
  returns entries in the same shape as the Cloud Logging reader, preserves the
  order Batch wrote them in, reads whole objects (no result cap, so long logs are
  not silently truncated), decodes lossily so a job printing binary output cannot
  break log retrieval, and honours a requester-pays billing project recorded on the
  job. Logs read from a `--logs-bucket` job preserve output order: the interleaved
  `output-` object is read instead of separate per-stream objects, so stderr lines
  emitted mid-run keep their original position, and the Batch agent's own lines are
  dropped by stream tag.
- `gc-batch logs print` and `logs download` exit 1 when log retrieval fails, so a
  wrapper script can tell a 403 from a job that simply produced no output; a
  successful read of zero entries exits 0 and reports `No log entries matched the
  query`. For the same reason `BatchLogging._query_cloud_logs`, `print_logs_for_job`,
  and `download_logs_for_job` raise on API errors rather than swallowing them, and
  the two public methods return the number of entries handled;
  `get_instance_id_from_logs` returns `None` when its query fails. An unrecognised
  `--severity` value is rejected with a clear error when reading logs from a
  bucket, instead of silently matching nothing.
- `gc-batch status` on a job that logs to a bucket points at the bucket instead of
  offering a Cloud Logging console URL with nothing behind it, and `logs filter` /
  `logs url` say plainly that their Cloud Logging query will match nothing for such
  a job. `gc-batch status` on a failed job that produced no logs at all adds a
  clearly labelled inference that the container never started and the image
  probably could not be pulled, naming the image URI. The Batch API never states
  this reason — the only failure text is "… with exit code 1" — so it is presented
  as an inference, not as something Batch reported.
- `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, and this changelog.
- CI running `ruff`, `mypy` (blocking), `pytest`, and a strict docs build across
  Python 3.10-3.13.

### Documentation

- Documentation for using gc-batch as a Python library: a [Python API
  guide](docs/guides/python-api.md) covering submission, polling, filtering, logs,
  mounts, settings, job profiles, fan-out, and error handling, plus library
  examples in the README and alongside the CLI example workflows.
- Troubleshooting covers the two ways log retrieval comes up empty: a job that
  failed before its container started (no task logs and no GCS objects are written,
  and the Batch API never states the reason), and `403 Permission denied for all log
  views`, which is the normal state in restricted environments and is solved by
  creating jobs with `--logs-bucket`. Includes how to tell an unreachable registry
  from a bad image reference, the `/bin/bash` entrypoint requirement, and the
  per-task log object naming.
