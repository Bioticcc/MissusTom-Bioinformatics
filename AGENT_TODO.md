
# Priority TODOs

## Jobs / Run Logging and Progress Visibility

- Improve Jobs/run logging for long-running and quiet operations.
  - Users should never have to infer whether a run is still active from one old log line.
  - Surface meaningful Missus Tom lifecycle events in Jobs:
    - queued
    - preparing
    - starting
    - running
    - current workflow/stage
    - finishing
    - cleanup
    - completed / failed / cancelled
  - Forward useful subprocess/task output where possible instead of showing only Nextflow process submission and final completion.
  - Investigate surfacing Nextflow task `.command.out` / `.command.err` output when appropriate.
  - Surface R analysis progress messages that are already emitted by the Bulk RNA-seq analysis script.
  - Add periodic "still running" / heartbeat messages with elapsed time during legitimately quiet operations.
  - Use real measurable progress when available.
  - Never invent percentages or fake progress.
  - Clearly distinguish raw command/subprocess output from Missus Tom-generated lifecycle/progress messages.

## Jobs Time / Terminal-State UI

- Correct Jobs time/status behavior after a run reaches a terminal state.
  - `Elapsed` should freeze when the run finishes.
  - `Finished` should reliably be populated for terminal runs.
  - `Last output: Xm ago` currently continues increasing after a completed run; freeze it or change its meaning/display for terminal runs.
  - Cleanup warnings should not make a scientifically successful run appear to still be running or generically interrupted.
  - Represent workflow execution failure separately from cleanup failure/warning.

## Stop / Cancel Run Control

- Add an explicit Stop/Cancel Run control for active Jobs.
  - Visible only while a run is queued, preparing, starting, or running.
  - Require confirmation before cancellation.
  - Show a clear transitional state such as `Stopping...`.
  - Use the existing controlled cancellation/containment endpoint rather than directly killing arbitrary PIDs.
  - Preserve logs and run history.
  - Distinguish `Cancelled by user` from `Failed` and `Interrupted`.
  - Disable repeated cancellation requests while cleanup is already underway.
  - Ensure cancellation handles preparation/reference-building and active Nextflow execution safely.

## Setup / Backend Diagnostics UX

- Improve Setup and backend diagnostics visibility.
  - Show useful live startup/setup output when operations take significant time.
  - Clearly indicate when dependency installation has completed and been verified.
  - Avoid leaving the user unsure whether Setup succeeded.
  - Remove or redesign persistent/redundant informational banners such as `Compatible Bulk backend connected.` when they provide no actionable information.

## Detect Native Execution / systemd Problems During Setup

- Detect native resource-containment requirements during Setup instead of waiting until Start Run.
  - Local/native execution requires a usable systemd user session and cgroup v2 containment support.
  - Setup/preflight should determine whether:
    - systemd is PID 1 where required
    - `XDG_RUNTIME_DIR` points to a valid user runtime directory
    - the systemd user bus exists
    - `systemctl --user` is operational
    - required cgroup controllers are available
    - an actual owned workload can be launched/contained using the supported mechanism
  - Detect WSL2 specifically where useful.
  - If WSL2 is running without systemd, provide actionable instructions:
    - add `[boot]` / `systemd=true` to `/etc/wsl.conf`
    - close WSL
    - run `wsl --shutdown` from Windows
    - reopen Ubuntu
  - Do not label systemd/cgroup configuration failures merely as `Insufficient resources`; distinguish environment/configuration incompatibility from actual CPU/RAM shortages.
  - Do not allow Setup and project validation to appear completely healthy when Start Run is guaranteed to fail because containment is unavailable.
  - Preserve Docker execution as an alternative where appropriate.

## WSL Native Containment Compatibility

- Ensure native containment works correctly on supported WSL2 + systemd environments.
  - Observed on WSL 3.0.1.0 / kernel 6.18.40.1-1 with systemd enabled.
  - WSL shell processes may originate in:
    - `0::/non-systemd`
  - systemd user manager is correctly delegated:
    - `Delegate=yes`
    - `DelegateControllers=cpu memory pids`
    - user cgroup controllers/subtree controls include `cpu memory pids`
  - `systemd-run --user --scope` successfully launches a process directly inside a user scope.
  - Current Missus Tom implementation instead creates a keeper scope, launches an independent child, and manually writes that PID into the scope's `cgroup.procs`.
  - On WSL this PID migration fails with:
    - `PermissionError: [Errno 13] Permission denied`
  - Rework containment so supported environments do not depend on migrating a process from `/non-systemd` into the systemd user hierarchy when systemd can place the process correctly at launch time.
  - Preserve:
    - CPU limits
    - memory limits
    - TasksMax
    - preparation containment
    - workflow containment
    - cancellation
    - cleanup
    - process ownership
    - recovery
    - stdout/stderr capture
  - Do not solve this by disabling containment or weakening resource-safety guarantees.


## Required focused and final validation

Run focused tests after each fix, then run the complete non-destructive suite.
At minimum:

    cd backend
    .venv/bin/pytest -q \
      tests/test_runs.py \
      tests/test_run_containment.py \
      tests/test_bulk_references.py \
      tests/test_preflight_bulk.py \
      tests/test_kallisto_timeout.py \
      tests/test_dependency_installation.py \
      tests/test_dependency_api.py \
      tests/test_bulk_rnaseq_analysis_r.py

    cd ../desktop
    npm run test:wizard
    npm run test:api
    npm run lint
    npm run typecheck
    npm run build
    npm run test:bundle

    cd ..
    Rscript -e "parse(file='workflows/bulk_rnaseq/bin/bulk_rnaseq_analysis.R')"
    nextflow config workflows/bulk_rnaseq -profile local > /tmp/missus-tom-nextflow-local.config
    nextflow config workflows/bulk_rnaseq -profile docker > /tmp/missus-tom-nextflow-docker.config
    ./scripts/check.sh
    cargo check --quiet --manifest-path desktop/src-tauri/Cargo.toml

Also complete these previously skipped validations when their isolated
prerequisites are available:

- all executable R fixtures with DESeq2, tximport, and ggplot2 installed from
  the committed lock;
- live systemd user-scope recovery/descendant containment;
- the controlled OOM containment probe with
  `MISSUS_TOM_CONTAINMENT_OOM_TEST=1`;
- sidecar and Debian construction using the packaging extras/PyInstaller;
- extracted-package frontend/backend revision and capability checks.

Do not run the user's generalized FASTQ dataset. Report clean-machine install,
real-data execution, native-versus-Docker scientific equivalence, and release
readiness as unverified unless each is separately performed.

## Required Cursor completion report

The final response must list:

- exact starting and ending commits and whether work remains uncommitted;
- every file materially changed;
- the exact generated lock identity and locked R/Bioconductor versions;
- focused and full test results, including every skip;
- containment recovery, assignment-failure, wrapper-signal, and package-revision
  evidence;
- whether the Debian artifact was built and inspected;
- every remaining blocker or unverified claim.


