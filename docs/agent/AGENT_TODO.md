# AGENT_TODO.md
# NOTE: From now own, KEEP completed todolist items as an archive of changes.

## Priority TODOs (ASAP):
1. **[P1-02/P1-03] Make workflow and biological-metadata identity fail closed.**
   - `backend/src/missus_tom/services/pipeline_sources.py:61-67,188-192`: `_read_active()` returns `None` for a missing file, unreadable file, malformed JSON, and an invalid `revision_id`. `resolve_active_root()` interprets `None` as the official workflow. Preserve the existing missing-file behavior, but raise a clear blocking error when `active.json` exists but cannot be read or is invalid. Never silently switch a declared custom workflow to official sources. Keep the selected revision in run provenance.
   - `backend/src/missus_tom/services/metadata.py:12-17,89-121`: legacy normalization can collapse distinct `SampleID` rows; a leading-`n` row is automatically preferred even when its condition/batch/replicate differs. Make conflicting many-to-one matches blocking and require user resolution. Retain only an explicit compatibility path for biologically equivalent duplicates, and record the selected original metadata row for every imported sample.
   - Tests: add malformed/unreadable/invalid `active.json` cases to `backend/tests/test_pipeline_sources.py`; add conflicting-versus-equivalent normalized duplicate cases to `backend/tests/test_metadata.py`; verify a run cannot start until either ambiguity is resolved. Preserve official execution when no activation file exists.

2. **[P1-01] Establish ownership of the packaged local API before a release.**
   - `desktop/src-tauri/src/lib.rs:23-24` launches the sidecar at predictable `127.0.0.1:8765`; `backend/src/missus_tom/main.py:36-47` has CORS but no authentication; state-changing routes include `backend/src/missus_tom/api/routes.py:551-566,574-581,621-632` and other POST endpoints.
   - Generate a cryptographically random secret per desktop launch, pass it only to the sidecar through a controlled host-to-sidecar mechanism, and require it on all state-changing API requests. Prefer an ephemeral port if this can be made reliable with startup/recovery. Use Origin/Fetch-Metadata validation only as defense in depth; CORS is not authentication.
   - Tests: unauthorized local POSTs cannot start/cancel a run, stop the backend, save project/pipeline state, or install dependencies; valid desktop requests still work; secret/port are absent from logs and run provenance. Document the residual same-OS-user threat boundary rather than claiming complete local-malware protection.

3. **[P1-04/P1-05] Make ONT execution and release inputs reproducible.**
   - `backend/src/missus_tom/services/dependencies.py:62-80,696-740`: Bulk uses `bulk-rnaseq-linux-64.lock`, but ONT dynamically solves unconstrained `samtools`, `htslib`, `python=3`, `r-base`, and subsequently installs R/Bioconductor packages.
   - `backend/pyproject.toml:11-29` allows compatible Python ranges, and `.github/workflows/release-linux.yml:30-33,49-53` installs moving Rust `stable` and resolves Python packages from the network. `desktop/package-lock.json` and `desktop/src-tauri/Cargo.lock` already protect their respective graphs; preserve them.
   - Create/package an explicit ONT lock, define a reproducible R/Bioconductor installation, record lock/environment identity in ONT run provenance, pin the Rust toolchain, and create a hash-checked Python build lock. Tests must verify lock completeness, installed versions, packaged assets, provenance, and clean reconstruction without changing Bulk behavior.


## General TODOs (Before 1.0 / next major release):
1. **[P1-06] Triage and gate dependency vulnerabilities.**
   - `scripts/check.sh:17-35` has no vulnerability-policy stage. The v0.4.7 CI report showed two high-severity npm advisories, but this alone does not prove runtime exploitability.
   - Identify the exact package, advisory, dependency path, affected build/runtime surface, available remediation, and any justified temporary exception. Add a policy-driven release gate with documented severity/exception behavior; do not blindly fail releases for irrelevant tooling-only advisories.
   - Tests: fixture or script coverage proves remediable policy violations fail and approved, time-bounded exceptions are visible.

2. **[P1-07] Make scientific and native CI evidence explicit.**
   - `backend/tests/test_bulk_rnaseq_analysis_r.py:19-48` skips all R integration tests without R/DESeq2/tximport/ggplot2. `backend/tests/test_run_containment.py:386-390,421-459` skips without Linux user-systemd/cgroup support; the OOM probe additionally requires `MISSUS_TOM_CONTAINMENT_OOM_TEST=1`.
   - Add required, named R/Bioconductor and native Linux containment jobs where these prerequisites exist. Keep the OOM test isolated/scheduled because it is intentionally disruptive. A normal fast CI job may still skip them, but release evidence must show the designated jobs actually ran.
   - Do not represent CI success as real-dataset scientific equivalence or native GUI acceptance; retain those as manual validation limits.

3. **[P2-01] Bound renderer command-log memory without losing full logs.**
   - `desktop/src/components/LiveCommandLog.tsx:50-60,96-103,134-145`: the preview is capped at 131,072 characters, but `fullTextRef.current` retains every chunk so copy/save grows without bound.
   - Retain only a bounded tail in the renderer. Move complete-log export/copy retrieval to backend/native storage or a streamed file path. Preserve incremental offsets, follow behavior, copy/save UX, and current run logs.
   - Tests: simulate a very large log; renderer retention stays bounded; saved/exported output remains complete and ordered.

4. **[P2-02] Treat failed resource measurements as unknown, not healthy.**
   - `backend/src/missus_tom/services/resource_monitor.py:38-68`: host/disk probe exceptions become `None`; `check()` resets the pressure counter when no reason is returned. Existing tests deliberately encode this behavior at `backend/tests/test_resource_monitor.py:70-101`.
   - Model healthy, pressured, and unavailable observations. Do not reset sustained-pressure debounce on an unknown sample; warn/escalate after sustained monitoring loss without immediately cancelling for one transient failure. Update the existing tests to prove both transient and repeated failures are safe.

5. **[P2-04/P3-01] Preserve useful API startup errors and close the abort race.**
   - `desktop/src/api.ts:41-60` builds a packaged-sidecar error including startup logs, but `apiRequest()` replaces it at `:150-158` with an incorrect development-port-8000 instruction. Preserve the original packaged diagnostic and only use the dev instruction in development.
   - `desktop/src/api.ts:70-75` registers an abort listener without first checking `signal.aborted`. Reject an already-aborted request immediately and retain listener cleanup.
   - Tests in `desktop/test/api.test.mjs`: packaged not-ready response retains its log; development fallback remains appropriate; already-aborted signal rejects without waiting.

6. **[P2-03] Strengthen recent-validation cache identity proportionately.**
   - `backend/src/missus_tom/services/projects.py:55-79` keys cached validation by path, size, and nanosecond mtime for five minutes. A deliberate same-size/same-mtime replacement can reuse stale validation.
   - Decide per input class: use stronger inexpensive metadata (for example inode/ctime where dependable) or content hashing for small, critical manifests; avoid blindly hashing multi-gigabyte FASTA/GTF files on every validation. Add a regression test that preserves size/mtime and document the selected tradeoff.

7. **[P2-05, deferred] Reduce New Project Wizard state-transition risk only when touching this area.**
   - `desktop/src/screens/NewProjectWizard.tsx:198-250,325-380`: many interdependent `useState` values are manually cleared in pipeline/stage transitions. This is a maintainability risk, not a demonstrated user-facing bug.
   - First add behavioral tests for pipeline switches, stage switches, settings import, and saved-project restore. Consider a focused reducer/state-transition helper during future wizard work; do not perform a speculative full rewrite.


## Completed (2026-10-26)

- Marked the Bulk RNA-seq Figures step as **(Experimental)** in its stepper and page heading.
- When Dashboard cannot reach the backend for readiness, it now points users to Setup to install the selected pipeline dependencies before returning to Dashboard.
- The launch-time `libEGL`/Mesa/Zink output is from the WSLg graphics stack failing to initialize hardware acceleration, not Missus Tom's backend or scientific workflows. No application-source change is appropriate. Verify the Windows GPU driver and WSL/WSLg installation with `wsl --version`, then update from an elevated PowerShell with `wsl --update` and restart it with `wsl --shutdown`. If the app window renders correctly after that, the remaining terminal output is non-blocking; if not, inspect `/mnt/wslg/{weston,stderr}.log`.

## ------------------------------------- End of TODO List Items -------------------------------------
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
