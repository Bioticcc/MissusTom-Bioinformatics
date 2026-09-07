# Reliability and workbench improvements

Completed development and synthetic validation on 2026-09-04. The reported
whole-PC freeze motivated the work; its original cause remains unconfirmed.

## Evidence and scope

The prior run's metadata and engine log showed 232 single-lane samples and
roughly 845 GiB of input reads. Several tasks overlapped despite a configured
parallel-task limit of one. The log ended abruptly, but accessible evidence did
not establish an out-of-memory event. Previous-boot kernel logs were unavailable.

Existing working-tree changes were preserved, with an initial ignored backup.
All development writes and synthetic fixtures stayed inside MissusTom. Other
repositories and the real sequencing inputs were not modified. This work did
not change the scientific R analysis; that file already had local changes.

## Delivered

- Whole-workflow CPU, memory, and task limits; Docker CPU/memory/swap bounds;
  bounded R threading; strict finite resource parameters; run-scoped labels.
- Host CPU/RAM/disk admission checks and a sustained-critical-pressure monitor.
- Single-lane trimming uses staged reads directly, avoiding an extra copy of
  original reads. Multi-lane order and existing work are preserved.
- Durable job recovery, process identity checks, inherited admission locks,
  bounded cancellation, scoped container cleanup, and fail-closed recovery.
  Persistence failures no longer prevent cleanup or strand an unmanaged child.
- Named Nextflow sessions and explicit resume from the same project, verified
  against real cached tasks. Saving a project cannot overwrite another project's
  output directory or mutate a manifest held by an active workflow.
- Recent/open-project flows, persisted local settings, cancellable API requests,
  non-overlapping polling, terminal logs, and refreshed results. Filesystem work
  uses API worker threads so it does not block the async health endpoint.
- A reproducible small synthetic workflow smoke script and updated operator and
  architecture documentation.

## Validation

- Final `scripts/check.sh`: 113 backend tests, five frontend tests, Python lint,
  formatting and typing, frontend lint and typing, and production build passed.
  The starting baseline had 68 backend tests.
- `cargo check --offline --quiet --manifest-path desktop/src-tauri/Cargo.toml`
  passed. This does not substitute for a packaged native-app interaction test.
- Headless Firefox exercised the real API and UI: recent project opening,
  persisted settings, job logs, results selection, and navigation.
- Nextflow config/preview checks and a generated trimming-script harness covered
  invalid resources, single-lane input handling, and multi-lane ordering.
- Real Docker/Nextflow execution on four synthetic paired-end samples and
  24 transcripts completed all 19 tasks under a two-CPU/four-GiB task budget,
  with at most one task scheduled concurrently and no remaining run containers.
- Two real runs through the backend adapter and run manager completed. The
  second explicitly resumed the first and cached all 19 tasks. Both released
  admission, survived durable-record reload, and left no labelled containers.

Temporary evidence is ignored under `.agent-work/`. Reproduce the small pipeline
check with `scripts/agent/synthetic-workflow-smoke.sh`; see the workflow guide
for prerequisites. Synthetic API tests required execution outside the command
sandbox because its async socket/thread wakeups stalled; the approved execution
passed without that environment failure.

## Remaining validation

The real 232-sample dataset was not rerun. Synthetic success verifies orchestration
and representative analysis execution, not scientific validity or full-scale
stability. Restart the backend and desktop to load the changes before evaluating
the saved project. A monitored real-data run is still needed to assess behavior
at the original scale; historical interrupted work is preserved for recovery.
