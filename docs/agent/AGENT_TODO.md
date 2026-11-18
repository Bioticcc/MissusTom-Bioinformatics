# AGENT_TODO.md

## General TODOs:
- make the desktop GUI icon the EyeSpy logo.
- look into an "Update" button in settings that automatically finds and installs the most recent release, then restarts the backend and app.

## Remaining implementation work

1. **[P1-06, partially implemented] Finish vulnerability triage and policy.**
   - The npm audit gate already exists in `scripts/audit-dependencies.mjs`, runs
     through `scripts/check.sh`, and has failure-report fixtures in
     `desktop/test/auditRemediation.test.mjs`. Do not reimplement that gate.
   - Still document the exact advisory/package/dependency path, build-versus-runtime
     exposure, and available remediation for findings. Current behavior blocks
     every high/critical advisory, including development dependencies, and blocks
     incomplete/service-error reports.
   - Define and document exception behavior. If exceptions are permitted, make
     them advisory-specific, justified, visible, and time-limited; add tests for
     approved, expired, and unmatched exceptions. The current script has no such
     mechanism or exposure-based policy. Do not mark this item complete merely
     because a vulnerability gate exists.

## Outstanding validation and release evidence

1. **[P1-07] Verify execution of the scientific/native CI jobs.**
   - Named locked R/Bioconductor, Linux containment, and isolated scheduled/manual
     OOM jobs are implemented in `.github/workflows/scientific.yml`. CI invokes
     that workflow and release builds depend on it. The R and containment jobs
     reject skipped or empty JUnit evidence through `scripts/assert-test-execution.py`.
   - The workflow is currently untracked in this working tree. Before release,
     retain successful job evidence for the final reviewed commit: executable R
     fixtures, live descendant containment, and the isolated OOM probe when due.
     Workflow definitions alone do not establish that those jobs ran.
   - Preserve the distinction between automated fixtures, real-dataset scientific
     equivalence, and native GUI acceptance.

2. **[P1-04/P1-05] Verify clean-machine reconstruction and current packaging.**
   - ONT/R package locking, runtime lock checks/provenance, the pinned Rust
     toolchain, and hash-checked Python build requirements are implemented.
     Keep those completed code changes; this is a validation task.
   - Verify clean-machine installation and package the final reviewed tree,
     including the newer pinned Modkit repair. Record lock identities and
     resolved R/Bioconductor versions, inspect the Debian artifact, smoke-test
     the extracted backend, and check frontend/backend revision and capability
     agreement. Prior package evidence does not certify the current uncommitted
     workflow/dependency changes.
   - Do not independently commit, push, merge, tag, package, or release without
     user authorization.

3. **Complete the remaining native/scientific acceptance checks in isolation.**
   - Verify native Linux/WSL GUI startup diagnostics, authenticated local API
     requests, and complete on-disk command-log exports in the packaged app.
   - Verify containment recovery, assignment-failure handling, wrapper signals,
     and the controlled OOM probe with suitable isolated prerequisites.
   - Track real-data workflow completion, native-versus-Docker scientific
     equivalence where applicable, and clean-machine behavior separately. Do not
     claim these from unit tests, skipped tests, or configuration review.

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
