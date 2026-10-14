# AGENT_TODO.md

## HIGH PRIORITY — Desktop GUI Performance and Responsiveness [CODEX] - [Awaiting Manual Testing]

### Observed Problem

Missus Tom has exhibited significant GUI lag, slow scrolling, delayed navigation, and intermittent unresponsiveness on three separate test machines, including a powerful native Linux workstation and WSL2 Ubuntu installations.

On WSL2, application startup produces graphics warnings involving Mesa, EGL, and Zink:

- `MESA: error: ZINK: failed to choose pdev`
- `libEGL warning: egl: failed to create dri2 screen`
- `libEGL warning: failed to get driver name for fd -1`

These warnings may indicate graphics initialization problems or fallback rendering, but they do not establish the root cause of the application-wide lag.

### Required Investigation

1. **Graphics and Rendering**
   - Identify the graphics renderer actually used by Missus Tom on each platform.
   - Determine whether hardware acceleration is working or software rendering is being used.
   - Investigate WebKitGTK, GTK, Mesa, EGL, and WSLg compatibility.
   - Determine whether rendering failures or fallback paths contribute to poor performance.
   - Do not force software rendering or disable GPU acceleration globally without comparative evidence.

2. **Frontend Performance**
   - Profile React rendering and unnecessary component re-renders.
   - Investigate navigation delays, scroll jitter, UI freezes, and large log rendering.
   - Inspect polling frequency, overlapping requests, and repeated state updates.
   - Ensure lengthy operations do not block the UI thread.
   - Investigate expensive component mounting, layout recalculation, and rendering.

3. **Backend Responsiveness**
   - Profile API response times during normal operation and active pipelines.
   - Identify synchronous or CPU-intensive operations blocking backend responses.
   - Ensure validation, dependency checks, reference preparation, and filesystem scans remain asynchronous where appropriate.
   - Verify backend activity does not cause frontend navigation or rendering to stall.

4. **Resource Usage**
   - Measure CPU, RAM, and GPU utilization while the application is idle, navigating, scrolling, and executing a pipeline.
   - Investigate unnecessary background work and resource contention.
   - Distinguish rendering bottlenecks from backend stalls and operating-system issues.

### Required Fixes

- Resolve confirmed application-level performance bottlenecks.
- Correct graphics initialization problems where practical and supported.
- Reduce unnecessary rendering, polling, and background processing.
- Keep the interface responsive during long-running operations.
- Preserve all existing functionality, scientific pipeline behavior, and resource containment.

### Validation Requirements

- Establish reproducible performance benchmarks before making changes.
- Compare measurements before and after each significant fix.
- Test on native Linux and WSL2 Ubuntu.
- Verify smooth scrolling, responsive navigation, and reliable UI interactions.
- Test responsiveness during idle operation, project validation, active jobs, and large log output.
- Confirm performance fixes introduce no regressions.
- Do not mark this task complete solely because graphics warnings disappear; actual user-facing responsiveness must measurably improve.

**Release priority: HIGH — Must be resolved and validated before stable v0.4.0.**

## Fix Open Output Folder — WSL File Explorer Integration [CODEX] - [Awaiting manual testing]

- Fix the **Open Output Folder** button in Jobs, Results, and other relevant screens.
- Currently, clicking the button in WSL Ubuntu can launch Google Chrome instead of a file manager.
- The current implementation uses `xdg-open`, which may open a browser when no Linux file manager is installed or correctly associated with directories.

### Required Changes

- **WSL Ubuntu:** Automatically detect WSL and open the requested output directory using Windows File Explorer (`explorer.exe`).
- **Native Linux:** Continue using the system's default graphical file manager through `xdg-open`.
- Ensure the correct output directory is opened, not merely the application's general output folder.
- Handle paths containing spaces and special characters safely.
- If opening the directory fails, display a meaningful error and provide a copyable directory path.
- Do not require WSL users to install a separate Linux file manager.

### Validation Requirements

- Verify behavior on both WSL2 Ubuntu and native Linux.
- Test all relevant folder-opening buttons.
- Confirm that opening completed results never launches a web browser unintentionally.
- Ensure the change does not interfere with pipeline execution, generated results, or existing project paths.

## Jobs / Run Logging and Progress Visibility [CODEX] - [Awaiting manual testing]

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

## Jobs Time / Terminal-State UI [CODEX] - [Awaiting manual testing]

- Correct Jobs time/status behavior after a run reaches a terminal state.
  - `Elapsed` should freeze when the run finishes.
  - `Finished` should reliably be populated for terminal runs.
  - `Last output: Xm ago` currently continues increasing after a completed run; freeze it or change its meaning/display for terminal runs.
  - Cleanup warnings should not make a scientifically successful run appear to still be running or generically interrupted.
  - Represent workflow execution failure separately from cleanup failure/warning.

## Stop / Cancel Run Control [CODEX] - [Awaiting manual testing]

- Verify and complete the existing Stop/Cancel Run control for active Jobs.
  - Visible only while a run is queued, preparing, starting, or running.
  - Require confirmation before cancellation.
  - Show a clear transitional state such as `Stopping...`.
  - Use the existing controlled cancellation/containment endpoint rather than directly killing arbitrary PIDs.
  - Preserve logs and run history.
  - Distinguish `Cancelled by user` from `Failed` and `Interrupted`.
  - Disable repeated cancellation requests while cleanup is already underway.
  - Ensure cancellation handles preparation/reference-building and active Nextflow execution safely.

## Setup / Backend Diagnostics UX [CODEX] - [Awaiting manual testing]

- Improve Setup and backend diagnostics visibility.
  - Show useful live startup/setup output when operations take significant time.
  - Clearly indicate when dependency installation has completed and been verified.
  - Avoid leaving the user unsure whether Setup succeeded.

## Setup Banner Cleanup [CODEX] - [Awaiting manual testing]

- Remove or redesign persistent/redundant informational banners such as `Compatible Bulk backend connected.` when they provide no actionable information.
- Preserve important error messages, warnings, and actionable status indicators.
- Do not modify backend logic or dependency validation.
- Run relevant frontend tests.

## Detect Native Execution / systemd Problems During Setup [CODEX] - [Awaiting manual testing]

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

## Loaded Project Management [CODEX]

- Users should be able to modify all settings when opening an existing project.
- Any changes must invalidate previous validation results and require successful revalidation before running.
- Ensure the updated project manifest, run plan, and saved settings remain consistent.
- Preserve existing results and project history unless the user explicitly requests otherwise.

## UI Button/Input X Bug [CURSOR]

- When the application window is smaller than fullscreen, X-shaped overlays appear on buttons and inputs.
- The artifacts disappear when returning to fullscreen.
- Investigate CSS, SVG, and responsive layout behavior.
- Implement a minimal fix if the cause is isolated to frontend styling.
- If the cause involves WebKitGTK, GPU rendering, or native window behavior, report the findings and defer the fix to Codex.
- Verify behavior at multiple window sizes without introducing layout regressions.

## WSL Native Containment Compatibility [CODEX — DONE]

- Ensure native containment works correctly on supported WSL2 + systemd environments.
  - Observed on WSL 3.0.1.0 / kernel 6.18.40.1-1 with systemd enabled.
  - WSL shell processes may originate in:
    - `0::/non-systemd`
  - systemd user manager is correctly delegated:
    - `Delegate=yes`
    - `DelegateControllers=cpu memory pids`
    - user cgroup controllers/subtree controls include `cpu memory pids`
  - `systemd-run --user --scope` successfully launches a process directly inside a user scope.
  - Previous Missus Tom implementation created a keeper scope, launched an independent child, and manually wrote that PID into the scope's `cgroup.procs`.
  - On WSL this PID migration failed with:
    - `PermissionError: [Errno 13] Permission denied`
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
  - Do not solve regressions by disabling containment or weakening resource-safety guarantees.
  - No further implementation required unless regression testing identifies a problem.

## Required Focused and Final Validation [CODEX]

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

Also complete these previously skipped validations when their isolated prerequisites are available:

- all executable R fixtures with DESeq2, tximport, and ggplot2 installed from the committed lock;
- live systemd user-scope recovery/descendant containment;
- the controlled OOM containment probe with `MISSUS_TOM_CONTAINMENT_OOM_TEST=1`;
- sidecar and Debian construction using the packaging extras/PyInstaller;
- extracted-package frontend/backend revision and capability checks.

Do not run the user's generalized FASTQ dataset. Report clean-machine install, real-data execution, native-versus-Docker scientific equivalence, and release readiness as unverified unless each is separately performed.

## Required Completion Report [CODEX / CURSOR]

Each agent must report:

- Exact starting and ending commits and whether work remains uncommitted.
- Every file materially changed.
- Focused test results, including failures and skips.
- What was fixed and what remains unverified.
- Any remaining blockers or regressions.
- Whether a commit was created.

For tasks involving scientific dependencies, containment, packaging, or release validation, also report:

- Exact generated lock identity and locked R/Bioconductor versions, where applicable.
- Containment recovery, assignment-failure, wrapper-signal, and package-revision evidence, where applicable.
- Whether the Debian artifact was built and inspected.

Do not independently push, merge, tag, package, or release unless explicitly instructed.
