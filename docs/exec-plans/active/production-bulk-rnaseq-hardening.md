# Production Bulk RNA-seq Generalization and Hardening

## Objective

Finish and verify the generalized Bulk RNA-seq implementation so a normal user
can create a paired-end project using only:

1. paired FASTQ files;
2. a transcriptome FASTA; and
3. the matching annotation GTF.

Missus Tom must validate those references, derive the transcript-to-gene
mapping, and build or reuse a managed Kallisto index automatically when the run
starts. BioMart and a prebuilt Kallisto index must not be required for the normal
path.

This plan also covers all correctness, recovery, reproducibility, resource
containment, and validation defects identified during the return audit.

## Important diagnosis

The Step 6 UI reported during manual testing came from an older application
build, not from the current feature-branch source:

- Feature branch: feature/production-bulk-rnaseq
- Required starting commit: b28cd5d
- Parent main/release commit: 6961729, tagged v0.3.0-rc.12

The current feature branch already contains a Step 6 build mode that asks for
FASTA plus GTF and contains no normal BioMart field. The parent commit still
contains the old Step 6 that requires a supplied Kallisto index and human
BioMart table.

Both builds identify themselves as application version 0.3.0, making stale or
mixed builds difficult to recognize. Runtime/build provenance must therefore be
fixed before treating the UI problem as resolved.

The current feature-branch backend also already implements deferred reference
preparation:

- index identity is based on FASTA SHA-256 and Kallisto version;
- annotation identity is based on the normalization version and FASTA/GTF or
  supplied-mapping hashes;
- index and normalized mapping preparation occurs at run start;
- a per-run execution manifest receives the prepared index/mapping paths;
- Nextflow consumes the execution manifest, not a BioMart table.

Preserve this architecture while repairing the gaps below.

## Scope and safety constraints

Before editing, run:

    git status --short
    git branch --show-current
    git rev-parse HEAD
    git log --oneline -n 5

The implementation must obey these constraints:

- Work from feature/production-bulk-rnaseq at b28cd5d or a descendant that
  explicitly contains that commit.
- Preserve the user's existing modification to AGENT_TODO.md. Do not edit,
  revert, stage, overwrite, or reformat it.
- Do not modify ../BulkRnaSeq, ../ONTAnalysis, scientific input data, installed
  managed environments, or active runs.
- Do not launch the user's generalized FASTQ dataset.
- Do not require Docker for normal installation, validation, or execution.
- Do not silently reinterpret a BioMart table as a Kallisto index or normalized
  transcript mapping.
- Retain BioMart handling only for recognizing legacy manifests and returning
  an actionable migration error.
- Keep the ONT environment and runtime independent from Bulk RNA-seq.
- Keep fixed argument arrays, shell=False, loopback-only networking, validated
  paths, and the local-only data boundary.
- Follow AGENTS.md and delegate bounded exploration, implementation, and review
  to the configured specialized agents.
- Implement in bounded stages and run focused checks after each stage.
- Do not claim clean-machine, real-data, scientific-equivalence, or release
  completion without directly performing those validations.

## Stage 1: Runtime provenance and stale-build prevention

### 1.1 Confirm the old/new UI difference

Inspect both versions:

    git show 6961729:desktop/src/screens/NewProjectWizard.tsx
    git show b28cd5d:desktop/src/screens/NewProjectWizard.tsx

The old source contains human BioMart and supplied-index requirements. The new
source contains referenceMode build, FASTA/GTF fields, and no normal BioMart
field.

Do not duplicate or blindly rewrite the already-present feature-branch UI.

### 1.2 Expose build compatibility through the backend

Primary files:

- backend/src/missus_tom/api/routes.py
- backend/src/missus_tom/config.py
- backend/src/missus_tom/__init__.py
- backend-sidecar packaging scripts
- desktop/src/types.ts
- desktop/src/api.ts
- desktop/src/App.tsx

Extend GET /health with stable build and capability information:

    {
      "name": "Missus Tom",
      "version": "<application release version>",
      "build_revision": "<git commit>",
      "manifest_schema_versions": ["1.0.0", "1.1.0"],
      "bulk_pipeline_versions": ["0.5.0"],
      "capabilities": {
        "bulk_fasta_gtf_reference_preparation": true,
        "bulk_managed_kallisto_index": true,
        "bulk_legacy_biomart_execution": false
      }
    }

Requirements:

- Inject the Git revision during sidecar/release construction.
- Use an explicit development value when no revision was injected. Do not
  invent a commit hash.
- Keep the response backward-compatible with the existing Tauri readiness
  parser.
- Display application version and abbreviated build revision in the existing
  version/about UI.
- Before allowing a new production Bulk project, verify that the backend
  advertises bulk_fasta_gtf_reference_preparation.
- If a new frontend connects to an old backend, block project creation with a
  specific compatibility error.
- Package the frontend and backend from the same revision.

Synchronize the next approved application release version across:

- backend/src/missus_tom/__init__.py
- desktop/package.json
- desktop/package-lock.json
- desktop/src-tauri/tauri.conf.json
- desktop/src-tauri/Cargo.toml when applicable
- hard-coded version/provenance UI fields

Do not leave materially different builds labeled only as 0.3.0.

### 1.3 Verify built and packaged assets

Add a release check that validates the emitted frontend bundle and packaged
backend, rather than only checking TypeScript source.

The check must prove:

- the built UI contains the new FASTA/GTF wording;
- the built UI does not contain the old human BioMart wizard wording;
- the packaged backend advertises the production Bulk capability;
- frontend and backend revisions match;
- the packaged workflow contains bulk_rnaseq_analysis.R rather than the removed
  fixed human analysis path.

Build and extract the Debian artifact in a temporary directory for inspection.
Do not install it automatically.

## Stage 2: Make Step 6 unambiguous

Primary files:

- desktop/src/screens/NewProjectWizard.tsx
- desktop/src/newProjectWizardContract.ts
- desktop/src/screens/RunPlanScreen.tsx
- desktop/src/types.ts
- desktop/test/newProjectWizard.contract.test.mjs

### 2.1 Normal quantification path

For Start with FASTQ files, Step 6 must prominently show only:

1. Transcriptome FASTA, required.
2. Matching annotation GTF, required.

Use clear wording:

> Missus Tom will validate the FASTA and GTF, derive the transcript-to-gene
> mapping, and build or reuse a managed Kallisto index when the run starts.

Also explain:

- the FASTA must contain transcript sequences, not a genomic FASTA;
- the GTF must come from the same annotation release;
- preflight validates identifier compatibility;
- index construction happens after Run pipeline is selected, not when the
  project is saved;
- reuse occurs only when FASTA content and Kallisto version match.

Every new quantification project must default to referenceMode build.

The generated manifest must contain:

    {
      "schema_version": "1.1.0",
      "pipeline_version": "0.5.0",
      "reference_mode": "build",
      "reference_resources": {
        "transcriptome_fasta": "/absolute/path/transcripts.fa",
        "annotation_gtf": "/absolute/path/annotation.gtf"
      },
      "parameters": {
        "start_stage": "quantification"
      }
    }

It must not contain biomart, kallisto_index, or transcript_to_gene in normal
build mode.

### 2.2 Existing-index mode is advanced

Do not present Use existing Kallisto index as an equal normal choice. Move it
under an explicit disclosure such as:

> Advanced: use an existing Kallisto index

When selected, require:

- Kallisto index; and
- annotation GTF or normalized transcript-to-gene mapping.

Add an optional field:

- Original transcriptome FASTA used to build this index.

If provided, retain it as reference_resources.transcriptome_fasta so preflight
can compare identifiers. If omitted, show a warning that a Kallisto index cannot
prove its own annotation compatibility.

Never rebuild an explicitly supplied index.

### 2.3 Analysis-only stays separate

For Skip quantification:

- require one abundance.tsv per included sample;
- require annotation GTF or transcript-to-gene mapping;
- do not display or require FASTQs, transcriptome FASTA, or Kallisto index;
- do not expose BioMart;
- preserve existing analysis-only manifest compatibility unless a deliberate
  schema migration is introduced.

### 2.4 Legacy loading behavior

Continue loading older manifests/debug exports for inspection, but:

- return a clear migration error for legacy BioMart-only projects;
- never reinterpret BioMart as an index or mapping;
- never invent FASTA/GTF paths;
- do not treat a missing reference_mode as a valid schema 1.1.0 project;
- preserve the original manifest until the user explicitly re-saves a migrated
  project.

## Stage 3: Correct strandedness presentation

Primary files:

- desktop/src/newProjectWizardContract.ts
- desktop/src/screens/NewProjectWizard.tsx
- related frontend tests and documentation

Do not change persisted values or workflow flags:

- forward maps to --fr-stranded;
- reverse maps to --rf-stranded;
- unstranded supplies no flag.

The current defect is the inverted first-/second-strand wording. Replace it
with orientation-based labels:

- Forward / FR: read 1 maps in transcript orientation; Kallisto uses
  --fr-stranded.
- Reverse / RF: read 1 maps antisense to the transcript; Kallisto uses
  --rf-stranded.
- Unstranded: no strandedness flag.

If first-/second-strand terminology is retained in help text, state that common
first-strand protocols are usually RF and common second-strand protocols are
usually FR, and instruct users to confirm their library kit.

Update UI help, documentation, demo metadata, and tests. Do not invert the
workflow flag mapping.

## Stage 4: Harden manifest and preflight reference validation

Primary files:

- backend/src/missus_tom/models/manifest.py
- schemas/project-manifest.schema.json
- examples/synthetic-project-manifest.json
- desktop/src/types.ts
- desktop/src/newProjectWizardContract.ts
- backend/src/missus_tom/services/preflight.py
- backend/src/missus_tom/services/bulk_references.py
- backend/tests/test_manifest.py
- backend/tests/test_schema.py
- backend/tests/test_preflight_bulk.py
- backend/tests/test_bulk_references.py

### 4.1 Turn file failures into blocking preflight checks

Mapping, GTF, and FASTA failures must become bulk_reference_contract blocking
checks rather than HTTP 500 responses.

Handle at least:

- missing file;
- permission failure;
- file disappearing during validation;
- invalid UTF-8;
- invalid gzip;
- malformed tabular rows;
- FASTA without transcript headers;
- GTF without usable transcript_id and gene_id attributes.

Normalize BulkReferenceError, OSError, UnicodeError, and gzip.BadGzipFile into
safe, resource-specific validation messages.

### 4.2 Reject ambiguous transcript mappings

Change read_supplied_transcript_to_gene so it tracks complete transcript
assignments instead of only a set of transcript IDs.

Rules:

- reject empty transcript or gene IDs;
- deterministically deduplicate or clearly reject identical duplicate rows;
- always reject one transcript mapped to different gene IDs;
- reject conflicting gene name or biotype metadata for the same transcript;
- preserve deterministic ordering in normalized outputs.

Add equivalent defensive validation in bulk_rnaseq_analysis.R. The R code must
not silently keep the first conflicting row.

### 4.3 Align overlap validation

For build mode:

- parse FASTA and GTF during preflight;
- apply the same transcript-ID normalization and at least 95 percent overlap
  policy used during preparation;
- do not build the index during preflight.

For advanced existing-index mode:

- when original FASTA plus mapping/GTF are supplied, run the same compatibility
  check in preflight;
- make mismatch blocking;
- if the original FASTA is absent, retain a visible compatibility-unverified
  warning.

Preflight and runtime preparation must use the same identifier policy.

### 4.4 Keep all contract representations aligned

If optional existing-index FASTA changes accepted combinations, update together:

- JSON Schema;
- Pydantic model;
- TypeScript types;
- wizard resource builder;
- synthetic example;
- schema, manifest, API, and frontend contract tests.

Do not bump the schema merely because an already-allowed optional resource is
now exposed by the UI.

## Stage 5: Make reference caching atomic, cancellable, and diagnosable

Primary files:

- backend/src/missus_tom/services/bulk_references.py
- backend/src/missus_tom/services/runs.py
- backend/src/missus_tom/models/run.py
- backend/src/missus_tom/pipeline_adapters/bulk_rnaseq.py
- reference/run tests

### 5.1 Preserve cache identities

Retain:

- Kallisto index identity from FASTA SHA-256 plus Kallisto version;
- annotation identity from normalization version and FASTA/GTF or supplied
  mapping hashes;
- application-owned cache below the state directory;
- immutable per-run execution manifests containing prepared paths and
  provenance.

Never key reuse only from path, filename, size, or modification time.

### 5.2 Publish mappings atomically

Write normalized mappings to a temporary file in the destination cache
directory, flush and close it, atomically replace the final file, and only then
write the completion marker.

A cache entry is reusable only when:

- completion marker exists and validates;
- identity matches;
- artifact exists and is nonempty;
- expected metadata/checksums match.

Never reuse an orphan partial file without a valid marker.

### 5.3 Make cache-lock acquisition cancellation-aware

Replace indefinitely blocking LOCK_EX with:

- LOCK_EX plus LOCK_NB;
- bounded retry/backoff;
- cancellation check between attempts;
- an operator-visible Waiting for reference cache stage;
- a sensible timeout and actionable error if the lock never clears.

Cancellation while waiting must reach CANCELLED, release run admission, and
leave the cache owner untouched.

### 5.4 Preserve failed build diagnostics

_mark_failed must not delete build.log.

On failure:

- retain stdout/stderr in build.log;
- retain failed.json;
- include the log path in the run error;
- append a bounded final diagnostic excerpt to the normal run log;
- remove only incomplete index artifacts and completion markers.

At the beginning of a new attempt, deliberately rotate or replace the previous
build log.

Test failed diagnostics and successful retry behavior.

## Stage 6: Make reference preparation crash-recoverable

The Kallisto preparation child is currently tracked only in memory. A backend
crash can leave it alive while the recovered run lacks a verifiable identity.

Use the existing persisted process identity fields because reference preparation
and Nextflow execution are sequential. Add an explicit persisted phase such as:

- queued;
- reference_preparation;
- reference_prepared;
- workflow_launch;
- workflow.

When Kallisto index construction starts:

- read PID, process group ID, process start ticks, and boot ID;
- persist those fields immediately;
- persist phase reference_preparation;
- pass the run's global and project admission-lock file descriptors into the
  child, as is already done for Nextflow;
- clear the identity only after the child has been reaped and the transition is
  persisted.

Recovery must:

- verify identity before signaling;
- distinguish preparation from workflow execution;
- use TERM, grace period, then KILL;
- hold admission until verified process-tree exit;
- treat an identity-free crash between phases as restartable/interrupted rather
  than an unknowable orphan;
- never signal a reused PID without matching start ticks and boot ID.

Add tests for:

- restart while Kallisto preparation is alive;
- cancellation after restart;
- TERM-to-KILL escalation;
- crash after preparation but before Nextflow launch;
- reused/stale PID rejection;
- inherited admission locks surviving parent failure;
- successful resume after preparation recovery.

## Stage 7: Restore hard resource containment for native runs

Nextflow CPU, memory, and queue settings are scheduling/admission directives.
They are not kernel-enforced resource limits.

Implement a Linux-native containment backend, preferably a per-run cgroup-v2 or
systemd user scope, covering both reference preparation and the complete
Nextflow descendant tree.

Requirements:

- one scope per run;
- hard memory limit from the workflow memory budget;
- CPU quota from the workflow CPU budget;
- bounded task/process count when supported;
- persisted scope identifier in RunRecord;
- cancellation/recovery terminates the entire scope;
- cleanup verifies the scope is empty before releasing admission.

Before relying on systemd-run --user, verify it from the packaged GUI
environment, including XDG_RUNTIME_DIR, the user bus, and supported WSL2
configurations.

If delegated cgroup controllers are unavailable:

- fail local execution closed with a specific preflight/setup result;
- give actionable enablement instructions;
- do not silently run without containment;
- keep Docker only as an explicit regression alternative, not a normal Setup
  prerequisite.

Tests:

- scope command and property construction;
- CPU quota conversion;
- memory limit conversion;
- unavailable-controller failure;
- cancellation and recovery by scope identity;
- Linux integration proving descendants belong to the capped scope;
- controlled memory-budget violation without destabilizing the workstation.

Do not claim resource-containment parity until the Linux integration test passes.

## Stage 8: Reproducible dependency installation and failed-candidate cleanup

Primary files:

- backend/src/missus_tom/services/dependencies.py
- dependency models/tests
- generated lock resources
- THIRD_PARTY_NOTICES.md when resolved software changes

### 8.1 Lock R and Bioconductor

The current Bulk catalogue leaves r-base, DESeq2, tximport, ggplot2, and
transitive packages unconstrained.

Generate a Linux x86-64 explicit Micromamba/Conda lock using the owning solver
tool. Lock:

- exact R version;
- exact Bioconductor release;
- exact DESeq2;
- exact tximport;
- exact ggplot2;
- all transitive R/native dependencies;
- all required Bulk CLI tools.

Prefer explicit artifacts with URLs and hashes over unconstrained channel
solving.

Requirements:

- do not hand-edit a generated lock;
- do not bundle the environment inside the Debian package;
- Setup downloads locked artifacts from the internet;
- Bulk and ONT remain separate environments;
- verify exact installed versions and required R namespaces before activation;
- record lock identity and resolved versions in run provenance.

### 8.2 Remove only failed candidates

Track whether activation occurred.

On pre-activation failure:

- remove only environments/<job-id>/;
- validate that the target is below the managed Bulk root;
- reject symlinks and escaping paths;
- never delete active, previous verified, or ONT environments;
- retain small job/log records for diagnosis.

Tests must prove failed candidates are removed and every active/previous/ONT
environment remains untouched.

## Stage 9: Fix scientific analysis edge cases and output provenance

Primary files:

- workflows/bulk_rnaseq/bin/bulk_rnaseq_analysis.R
- backend/tests/test_workflow_policy.py
- new executable R fixture tests

### 9.1 PCA dimensionality

Do not unconditionally access PC3.

After prcomp:

- determine the available PC count;
- produce 2D PCA only when at least two PCs exist;
- produce 3D PCA only when at least three PCs exist;
- when PC3 is unavailable, skip 3D artifacts and record the reason.

Do not fabricate PC3 values and call the result a valid 3D PCA.

A valid two-gene analysis must not crash because a third component does not
exist.

### 9.2 Evidence-based output contract

Replace unconditional generated statuses with per-artifact evidence.

output_contract.tsv should include at least:

    comparison_id
    analysis_class
    artifact
    status
    relative_path
    rationale

Allowed statuses:

- generated;
- skipped;
- failed.

Only mark an artifact generated after confirming that its expected file exists
and is nonempty.

Track per comparison and analysis class:

- all-gene, mRNA, and lncRNA DE outputs;
- 2D and 3D PCA;
- scree plot;
- heatmap;
- volcano and MA plots;
- p-value and adjusted-p-value histograms;
- fold-change density;
- sample-distance heatmap;
- DE-count plots;
- normalized matrices;
- provenance tables.

### 9.3 Execute the R regression

Add a small synthetic fixture that actually runs the analysis and covers:

- all-gene analysis without biotypes;
- optional mRNA/lncRNA classes;
- exactly two retained genes;
- missing PC3;
- insufficient heatmap genes;
- conflicting transcript mappings;
- numerator/denominator direction;
- generated/skipped output-contract rows;
- absence of fixed human ENST/ENSG assumptions.

Source-string tests alone are insufficient.

## Stage 10: Correct timeout classification

Primary files:

- workflows/bulk_rnaseq/bin/run_with_timeout
- backend/tests/test_kallisto_timeout.py

Do not infer a helper timeout only because elapsed time exceeded the limit and
the child returned 137 or 143.

Use an explicit watchdog-owned marker or state:

- return 240 only when this helper initiated the timeout TERM/KILL sequence;
- preserve genuine child or external exit status;
- do not report cancellation as a retryable timeout;
- do not rewrite an OOM SIGKILL as a timeout.

Test:

- success;
- ordinary nonzero exit;
- genuine helper timeout;
- late child self-TERM;
- late child self-KILL;
- external termination;
- timeout followed by forced KILL.

## Stage 11: Typed Setup errors

Primary files:

- backend/src/missus_tom/api/routes.py
- dependency service exception types
- backend/src/missus_tom/main.py
- desktop/src/api.ts
- desktop/src/screens/Setup.tsx
- API and frontend tests

Introduce stable error codes such as:

- dependency_install_in_progress;
- workflow_admission_locked;
- unsupported_pipeline;
- dependency_prerequisite_failed;
- dependency_verification_failed.

Status behavior:

- concurrent installation/run lock: 409;
- malformed request: 400 or 422;
- unsupported pipeline: 404;
- prerequisite/configuration error: non-conflict error;
- background job failure: install-job failure record.

Preserve error codes in ApiError. Setup must switch on code plus status, not
English regexes.

An arbitrary error containing the word installation must not be presented as a
concurrent-installation conflict.

## Stage 12: Focused and broad validation

### Frontend

    cd desktop
    npm run test:wizard
    npm run test:api
    npm run lint
    npm run typecheck
    npm run build

Add a built-bundle contract check after the Vite build.

### Manifest and references

    cd backend
    .venv/bin/pytest -q \
      tests/test_schema.py \
      tests/test_manifest.py \
      tests/test_preflight_bulk.py \
      tests/test_bulk_references.py \
      tests/test_bulk_rnaseq_adapter.py
    .venv/bin/mypy src

### Lifecycle, containment, and timeout

    cd backend
    .venv/bin/pytest -q \
      tests/test_runs.py \
      tests/test_resources.py \
      tests/test_kallisto_timeout.py

### Workflow parsing and synthetic execution

    Rscript -e "parse(file='workflows/bulk_rnaseq/bin/bulk_rnaseq_analysis.R')"
    nextflow config workflows/bulk_rnaseq -profile local > /tmp/missus-tom-nextflow-local.config
    nextflow config workflows/bulk_rnaseq -profile docker > /tmp/missus-tom-nextflow-docker.config

Run the new tiny native R/Nextflow fixture using synthetic inputs only.

### Broad non-destructive validation

    ./scripts/check.sh
    cargo check --quiet --manifest-path desktop/src-tauri/Cargo.toml

If packaging or build metadata changed:

    bash scripts/build-linux-sidecars.sh x86_64-unknown-linux-gnu
    cd desktop
    npm run tauri build -- --no-bundle

Build the Debian release through the documented release process and inspect it
under /tmp. Do not automatically install it.

## Acceptance criteria

Do not declare completion unless all applicable criteria are demonstrated:

1. The application displays the expected release version and Git revision.
2. New Bulk quantification projects default to FASTA plus GTF.
3. Normal Step 6 contains no BioMart or required prebuilt-index field.
4. Existing-index mode is clearly advanced.
5. Analysis-only requires abundance tables plus annotation, not an index.
6. Build-mode manifests contain FASTA/GTF and no BioMart/index.
7. Preflight handles incompatible and unreadable references without HTTP 500.
8. A first synthetic run builds the managed index and mapping.
9. An identical second run reuses the cache.
10. Changed FASTA content or Kallisto version invalidates index reuse.
11. Changed GTF content invalidates mapping reuse.
12. Failed builds retain actionable logs.
13. Cancellation while waiting for a cache lock completes cleanly.
14. Restart during index construction remains recoverable.
15. Native descendants are verifiably under hard resource limits.
16. Exact R/Bioconductor versions are installed and recorded.
17. Conflicting transcript mappings are rejected.
18. Two-gene analyses do not crash because PC3 is unavailable.
19. output_contract.tsv agrees with actual files.
20. Setup conflict behavior uses typed error codes.
21. The packaged Debian artifact contains the new UI and matching backend.
22. The full non-destructive check suite passes.
23. Clean-machine installation, real generalized-data execution, and
    native-versus-Docker scientific equivalence remain explicitly unverified
    until separately performed.

## Required completion report

Cursor's final report must state:

- exact starting and ending commits;
- why the user saw the old Step 6;
- files materially changed;
- manifest, API, cache, lifecycle, and output-contract changes;
- tests run with exact pass/fail/skip results;
- whether hard native containment was implemented and empirically verified;
- exact locked R/Bioconductor versions;
- whether a Debian artifact was built and inspected;
- what remains for the user's generalized FASTQ test;
- every partial or unverified requirement.

Do not claim production readiness from source inspection, mocked tests,
source-string assertions, or Docker-only smoke tests.
