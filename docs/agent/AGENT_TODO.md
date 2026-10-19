# AGENT_TODO.md

## General TODOs
- [Awaiting manual testing] On the setup screen, while installing the bolded "dependancies:" section says "awaiting your confirmation", however at no point does the user actually confirm anything. This is misleading, and unless it serves a purpose other then extra logs (which are already covered in the output terminal and other sections of the install) it should be removed or modified to give a move accurate output.

## BRS — Paired Biological Replicate Analysis [CODEX]

- Extend Bulk RNA-seq Experimental Design to support paired biological samples.
- Add an **Experimental Design Type** setting:
  - **Independent (default):** Treat each sample as an independent biological observation, regardless of Biological Replicate identifiers.
  - **Paired:** Use the existing Biological Replicate field to identify samples originating from the same biological subject.
- Do not automatically enable paired analysis because multiple samples share a replicate identifier.
- Preserve the current independent DESeq2 model: `~ condition`.
- For paired analysis, use: `~ biological_replicate + condition`.
- Reuse the existing Biological Replicate column rather than introducing a redundant Subject ID field.
- Require valid subject identifiers for paired analysis and validate matching samples across the compared conditions.
- Reject incomplete, ambiguous, or statistically invalid paired designs with clear explanations.
- Ensure biological sample counts and independent subject counts are handled appropriately during validation.
- Apply the selected statistical model consistently to all-gene, mRNA, and lncRNA analyses.
- Record the selected design type, subject assignments, and actual statistical model in the output metadata.
- Preserve backward compatibility with existing project manifests and the current independent-sample workflow.

### Validation Requirements

- Verify independent analysis produces the same results as the existing implementation.
- Validate paired analysis against a trusted DESeq2 paired-design example.
- Test missing subject IDs, incomplete pairings, duplicate assignments, and invalid designs.
- Ensure selecting paired mode does not modify or overwrite existing biological metadata.
- Verify the correct statistical model is recorded in the results.
- Run relevant frontend, backend, and R analysis tests.

## BRS — Batch-Effect Adjustment [CODEX]

- Add optional batch-effect adjustment to Bulk RNA-seq differential-expression analysis.
- Add an **Adjust for Batch Effects** setting in Experimental Design, disabled by default.
- Reuse the existing Batch column to identify processing batches.
- When adjustment is enabled, include batch in the DESeq2 statistical model:
  - **Independent samples:** `~ batch + condition`
  - **Paired samples:** `~ batch + biological_replicate + condition`, when statistically valid.
- Preserve the existing `~ condition` model when neither pairing nor batch adjustment is enabled.
- Validate that required batch assignments are present and consistent.
- Detect statistical confounding, including cases where batch and condition cannot be distinguished.
- Detect invalid combinations of subject, batch, and condition, including models with redundant factors.
- Block invalid designs rather than silently dropping factors or generating potentially misleading results.
- Apply batch adjustment consistently to all-gene, mRNA, and lncRNA analyses.
- Record batch assignments, adjustment settings, and the actual statistical model in output metadata.
- Preserve backward compatibility with existing projects and unadjusted results.
- Keep batch adjustment optional and avoid introducing unnecessary complexity into the default workflow.

### Validation Requirements

- Compare adjusted results against a trusted DESeq2 batch-adjusted example.
- Verify unadjusted analysis preserves existing behavior.
- Test missing batch values, confounded designs, and invalid paired/batch combinations.
- Confirm appropriate model selection for independent, paired, batch-adjusted, and combined designs.
- Verify batch metadata and statistical models are accurately recorded in the output.
- Run relevant frontend, backend, and R analysis tests.


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
