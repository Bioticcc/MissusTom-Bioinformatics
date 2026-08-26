# MVP architecture

## Implemented architecture

1. Preserve and inventory the existing pipeline as an external, read-only
   scientific baseline.
2. Make a versioned manifest the authoritative boundary between editable GUI
   proposals and future execution.
3. Put filesystem inspection, validation, persistence, and run planning in a
   loopback-only Python API.
4. Put every pipeline behind an adapter; restrict bulk RNA-seq execution to the
   validated internal human demo.
5. Build an accessible Tauri/React workbench around discovery, design, preflight,
   save, and plan workflows.
6. Run FastQC, MultiQC, Cutadapt, kallisto, tximport, and the fixed OD1-versus-H
   DESeq2 analysis through controlled containers.

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
  0.3.0 demo contains raw QC, paired trimming, clean QC, transcript
  quantification, mRNA/lncRNA DESeq2, and reporting. Container bases are pinned
  by registry digest and analysis package versions are recorded with outputs.
- **History** — a minimal SQLite table records saved project identity and
  manifest location. It is not a job database yet.

## Request flow

```text
React wizard
  -> POST /fastq/discover       -> metadata-only scanner
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
- `POST /api/v1/directories/preview`
- `POST /api/v1/projects/validate`
- `POST /api/v1/projects/save`
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

Job records store queued/preparing/running/completed/failed/cancelled state,
timestamps, command arguments, exit code, and a local log path. Run-state JSON,
Nextflow reports, scientific outputs, and the work directory persist under the
configured demo project. Work directories are never automatically deleted.

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
