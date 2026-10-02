
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


