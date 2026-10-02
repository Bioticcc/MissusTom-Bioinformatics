# Priority backlog

These items are not implemented yet. The preflight timeout is the highest-priority
correctness issue.

1. **PRIORITY — Fix Bulk Step 7 preflight timeout and missing checks.** When the
   generalized Bulk RNA-seq demo reaches Step 7, investigate why project
   validation can fail with “The local backend did not respond within 15
   seconds” instead of returning and displaying the individual passed and
   failed project checks. Preserve actionable backend errors and add regression
   coverage for the generalized demo manifest.

  This issue has already been investigated via health commands and terminal checks. The results are as such:
  Backend health and dependency endpoints are confirmed healthy on rc.21. /health returns status ok, and /api/v1/pipelines/bulk-rnaseq/dependencies returns 200 with all dependencies installed and missing: []. However, the Preflight Validation UI remains blank and shows the generic error “The local backend did not respond within 15 seconds.” Investigate the exact frontend API call used by the preflight step, its timeout handling, response parsing, and error mapping. The UI must distinguish a real backend health failure from a timeout/error in the specific preflight request.

2. On startup, if an already-running Missus Tom backend escaped normal shutdown,
   safely identify and stop that owned backend before starting the new app
   backend. Never terminate an unrelated process that happens to use the port.

3. Separate first-launch setup from the primary app. On the first launch, show
   only the existing Setup screen and its pipeline/setup options, not the
   Dashboard. After setup completes, let the user continue into the app. Add
   guidance that additional pipeline setup can be performed by creating a new
   project and installing requirements from the local setup section of Step 1.

4. Keep the setup debug terminal visible on the initial Setup screen while
   installs run and after they finish. Preserve the existing debug terminal in
   new-project setup as well, including completed output.

5. Replace the X-shaped input focus treatment with a simple green outline that
   matches the site colors.

# Minor backlog

These are deferred desktop polish items. The desktop UI owner should address
them without changing pipeline behavior or the local-only data boundary.

- Bubble containers around inputs and smaller information spots have corners
  cut off, causing an odd look. Solidify the borders of these containers and
  buttons.
- Add an “attempt automatic settings” button to the experimental design that
  uses file names/formatting to suggest experimental conditions. Warn that
  automatic labeling may be less accurate than manual labeling.

## Production Bulk RNA-seq audit status

The previously listed production hardening items 1–11 were audited against the
current implementation and focused tests and are complete. They were removed
from the active backlog. The broader validation work below remains open; do not
claim release readiness until its prerequisites and checks are complete.

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


