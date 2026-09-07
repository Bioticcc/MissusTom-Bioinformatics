# MVP architecture

## Implemented architecture

1. Preserve and inventory the existing pipeline as an external, read-only
   scientific baseline.
2. Make a versioned manifest the authoritative boundary between editable GUI
   proposals and future execution.
3. Put filesystem inspection, validation, persistence, and run planning in a
   loopback-only Python API.
4. Put every pipeline behind an adapter and validate supported bulk RNA-seq
   projects before execution.
5. Build an accessible Tauri/React workbench around discovery, design, preflight,
   save, and plan workflows.
6. Run FastQC, MultiQC, Cutadapt, kallisto, tximport, and manifest-defined
   two-group DESeq2 analyses through controlled containers.

No inspected incompatibility required deviation from the requested technology
stack.

## Components and ownership

- **Desktop (`desktop/`)** — Tauri 2 host plus React/TypeScript/Vite UI. It edits
  proposals and submits typed JSON. Native commands provide validated folder
  selection/opening; the UI cannot submit arbitrary commands.
- **Local API (`backend/`)** — FastAPI owns path normalization, FASTQ metadata
  discovery, validation, system inspection, atomic saving, planning, controlled
  execution, cancellation, logs, and result indexing.
- **Manifest (`schemas/`)** — JSON Schema 1.0.0 plus the matching Pydantic model.
  User-confirmed values are authoritative; filename parsing never assigns
  biology.
- **Adapters (`pipeline_adapters/`)** — a generic interface for availability,
  validation, stage/output descriptions, plans, and argument-array commands.
- **Workflow (`workflows/`)** — Nextflow DSL2 configuration and profiles. The
  human paired-end workflow contains raw QC, paired trimming, clean QC,
  transcript quantification, manifest-defined mRNA/lncRNA DESeq2 comparisons,
  and reporting. Container bases are pinned
  by registry digest and analysis package versions are recorded with outputs.
- **History** — SQLite records saved project identity and manifest location for
  dashboard reopening. Atomic JSON job records live in the application state
  directory and project logs. Recovery reads both the registry and legacy logs
  located through project history.

## Request flow

```text
React wizard
  -> POST /fastq/discover       -> metadata-only scanner
  -> POST /metadata/csv         -> local experimental-metadata parser and matcher
  -> POST /quantifications/discover -> existing kallisto abundance tables
  -> POST /directories/preview  -> selected folder's immediate metadata
  -> user edits proposals       -> biological confirmation
  -> POST /projects/validate    -> structural + project preflight
  -> POST /projects/save        -> atomic JSON + empty project layout
  -> GET  /demos/human          -> restricted pseudonymous demo manifest
  -> POST /runs/plan            -> adapter stages + argument-array preview
  -> POST /runs/start           -> controlled Nextflow process
  -> GET  /runs/{id}            -> status, logs, and existing result files
```

The backend binds to `127.0.0.1` during development. CORS accepts only the Vite
loopback origins. Paths must be absolute and are expanded/normalized before use.
The scanner does not follow symlinks or read FASTQ content. Subprocess checks use
fixed argument arrays, timeouts, and `shell=False` behavior. No frontend string
is interpreted as a command.

## API envelope

All success responses use `{success, data, errors, meta}`. HTTP and Pydantic
validation errors use the same shape with typed `code`, `message`, optional
`field`, and non-secret context. The implemented routes are:

- `GET /health`
- `GET /api/v1/system/preflight`
- `POST /api/v1/fastq/discover`
- `POST /api/v1/quantifications/discover`
- `POST /api/v1/directories/preview`
- `POST /api/v1/projects/validate`
- `POST /api/v1/projects/save`
- `GET /api/v1/projects`
- `POST /api/v1/projects/open`
- `POST /api/v1/runs/plan`
- `GET /api/v1/demos/human`
- `POST /api/v1/runs/start`
- `GET /api/v1/runs`
- `GET /api/v1/runs/{job_identifier}`
- `GET /api/v1/runs/{job_identifier}/logs`
- `GET /api/v1/runs/{job_identifier}/artifacts`
- `POST /api/v1/runs/{job_identifier}/cancel`
- `GET /api/v1/pipelines`
- `GET /api/v1/pipelines/bulk-rnaseq/status`

## Resumability and logging model

Job records store queued/preparing/running/cancelling/completed/failed/cancelled/
interrupted state, timestamps, command arguments, exit code, and a local log path.
Persisted admission state and Linux process identity support conservative
reconciliation after a backend restart. Global and project filesystem locks are
inherited by the child process. Cancellation retains admission until the process
group and job-labelled Docker containers have stopped. Engine logs are unique to
each run. Explicit Nextflow run names keep resume scoped to the same project;
legacy session names can be recovered from bounded local logs. Nextflow reports
and scientific outputs remain shared project outputs; work directories are never
automatically deleted. Saving uses the project lock too, preventing manifest
changes during an active run or replacement by a different project identity.

Blocking filesystem and runtime operations execute through FastAPI's worker pool.
Jobs fetches logs when expanded and performs a final refresh on completion.
Results uses abort and generation guards for selection and manual refresh so
stale responses cannot replace the selected run. Automatic polling waits for
each request to finish before scheduling another.

Execution admission compares workflow budgets against available CPU/RAM with
desktop reserves and estimates disk requirements on the output filesystem. The
Nextflow local executor applies total CPU, memory, and task-queue limits; Docker
enforces per-task CPU/memory/no-extra-swap limits. A lightweight runtime monitor
requests controlled cancellation after sustained critical host pressure. Policy
thresholds and user recovery steps are documented in `README.md`.

The Python logger emits local JSON and redacts values adjacent to common secret
labels. The application does not enumerate the environment or transmit logs.

## Sidecar evolution

Development uses separate Vite and Uvicorn processes. Later, build the Python
API into a pinned Linux executable, register it in Tauri `externalBin`, allocate
a loopback port, pass only named safe configuration, poll `/health`, and shut it
down with the window. API routes and frontend types remain stable through that
packaging change.

## Extensibility

The GUI speaks in manifests, stages, output categories, and job states rather
than Bash/R script names. A future single-cell or methylation adapter can provide
its own schema extension and stages without replacing dashboard, preflight,
jobs, results, or settings infrastructure.
