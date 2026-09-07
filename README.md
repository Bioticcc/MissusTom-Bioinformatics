# Missus Tom

Missus Tom is a local Yan Lab desktop application for bulk RNA-seq project
configuration, validation, and controlled workflow execution.

The enabled workflow accepts user-created human paired-end projects and the
included eight-sample human-data demo. It runs:

1. FastQC and MultiQC on raw paired reads.
2. Cutadapt with user-configured quality, minimum-length, and adapter settings.
3. FastQC and MultiQC on trimmed reads.
4. Kallisto 0.52.0 with a supplied compatible index and the selected library
   orientation.
5. Transcript-to-gene import for protein-coding and lncRNA gene classes.
6. DESeq2 differential expression for each manifest-defined two-group
   comparison, optionally restricted to an explicitly assigned intervention.
7. Normalized matrices, differential-expression tables, and the diagnostic
   plots used by the original human analysis scripts.

Enrichment and biological interpretation are not enabled. The existing
`../BulkRnaSeq` scientific baseline remains separate and read-only.

## Optional demo data

The prepared demo is stored at `/mnt/20TB_A/Adam/MissusTomDemo`. It contains four
H and four OD1 samples with 1,000,000 read pairs per sample. Public-facing sample
names and FASTQ headers use only these aliases:

- `DEMO_H_01` through `DEMO_H_04`
- `DEMO_OD1_01` through `DEMO_OD1_04`

The subsets remain restricted human sequence data. They are pseudonymized, not
anonymized. The demo root and directories use mode `0700`; derived FASTQs and
the separate source map use mode `0600`. No application function uploads data
or follows source-data symlinks.

## Prerequisites

- Linux
- Python 3.11 or newer
- Node.js 18 or newer and npm
- Rust/Cargo and the Linux Tauri 2 prerequisites
- Java 17 or newer
- Nextflow 24.04 or newer
- Docker Engine, with the current user permitted to access the daemon

The workflow uses digest-pinned public BioContainers images for FastQC 0.12.1,
MultiQC 1.33, Cutadapt 5.2, and Kallisto 0.52.0. Differential expression uses
the project-local `missus-tom/rnaseq-analysis:0.3.0` image built from the
digest-pinned Bioconductor 3.21 / R 4.5.2 base.

Build the analysis image once before running a workflow:

```bash
sg docker -c './scripts/build-analysis-image.sh'
```

## Start the application

The previous backend process must be stopped before starting the updated one.
From the terminal running Uvicorn, press `Ctrl+C`. Then run:

```bash
cd "$HOME/Desktop/Adam/MissusTom"
sg docker -c './scripts/dev-backend.sh'
```

Using `sg docker` is required until the desktop login session has been restarted
after adding the user to the Docker group. After a new login, this is sufficient:

```bash
./scripts/dev-backend.sh
```

In a second terminal:

```bash
cd "$HOME/Desktop/Adam/MissusTom/desktop"
npm run tauri dev
```

For a user project, select **New project** and choose either FASTQ
quantification or analysis-only input. FASTQ mode discovers paired reads and
requires a kallisto index plus BioMart. Analysis-only mode discovers one
Kallisto `abundance.tsv` per sample and requires BioMart, but not FASTQs or an
index. Review the biological design, add comparisons, validate, save, and run.
The design step can import the original human patient CSV, including `SampleID`,
`Condition`, `Batch`, `Patient`, and `Intervention`. Unsaved wizard settings can
also be exported and imported as JSON for debugging or continuation.

Use **Recent projects** on the dashboard to reopen a saved project, or **Open
project** to select its `input_manifest/project_manifest.json`. Missing inputs
are reported during validation without rewriting the saved manifest. **Settings**
saves the project parent folder and total CPU/RAM defaults locally for new projects.

On the run-plan screen:

1. Review the eight-stage run plan and selected-folder previews.
2. Choose **Resume previous run** to reuse completed tasks or **Start from
   beginning** to execute every task again.
3. Confirm **Quantification + analysis** for the complete FASTQ workflow or
   **Analysis only** to use discovered abundance tables or reuse complete
   kallisto outputs from this project.
4. Select **Run pipeline**.
5. Use **Jobs** for status and logs.
6. Use **Results** for files written by the workflow.

Runs use the persistent Nextflow work directory under the project. Resume targets
a recorded Nextflow session from the same project, preferring the same start
stage. With no eligible session, the run starts without a resume target. Older
projects can recover their session name from local logs. The start-from-beginning
option omits `-resume`, so completed tasks are not reused. Neither option deletes
existing work directories, results, or logs. Workflow code changes can invalidate
affected cached tasks even when resuming.

## Development setup

Create the project-local backend environment:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Install frontend packages locally:

```bash
cd ../desktop
npm install
```

Run all non-Rust checks:

```bash
cd ..
./scripts/check.sh
```

Run the native shell build check:

```bash
cd desktop
npm run tauri build -- --no-bundle
```

With Nextflow, Docker access, and the five workflow images already available,
run the complete pipeline on a small generated synthetic fixture:

```bash
./scripts/agent/synthetic-workflow-smoke.sh
```

This uses 2 CPUs, 4 GiB of task memory, and one task at a time. It writes only
synthetic reads, references, work, and results under ignored `.agent-work/`; it
refuses to pull missing Docker images. The check exercises the toolchain through
R analysis. It does not validate biological findings or full-project resource
needs.

## Execution controls

The backend launches an argument array with `shell=False`; it does not accept a
command from the GUI. Before starting, it checks all of the following:

- The optional local execution kill switch is enabled.
- The submitted manifest matches the saved manifest.
- The project is human, paired-end, Docker-based, and uses a supported pipeline
  version.
- FASTQs are regular files inside the selected input directory.
- Strandedness, adapters, trim settings, thresholds, and group sizes are valid.
- A readable kallisto index and human BioMart table are supplied.
- Every comparison references groups with the configured minimum sample count.
- Docker and Nextflow are available to the backend process.
- The total workflow CPU/RAM budget leaves capacity for the desktop and fits
  currently available memory, and the output filesystem has space for the run.

Only files inside the configured project output are indexed. Symlinks and files
outside the project root are excluded.

### Keeping the workstation responsive

CPU and memory settings are budgets for the **whole workflow**. The parallel-task
setting limits concurrent tasks across all stages. Each Docker task also has
hard CPU and memory limits and cannot expand into additional host swap. The
Nextflow JVM has a 1 GiB heap cap; analysis thread pools are bounded.

Before launch, the backend reserves 10% of logical CPUs (at least one, except on
a single-CPU host) and the greater of 2 GiB or 10% of total RAM for the desktop
and control processes. It checks the output filesystem against a conservative
estimate of four times the FASTQ input size plus 10 GiB, or twice the abundance
table size plus 10 GiB for analysis-only runs. These are capacity estimates, not
predictions of final output size. Resource warnings allow project setup; unsafe
resource requests block execution. Single-lane inputs go directly to Cutadapt,
avoiding an extra copy of each original FASTQ in the work directory.

During execution, the runner checks RAM and output disk space every five seconds.
Three consecutive critical observations request controlled cancellation: less
than 1 GiB free output space, or available RAM below the greater of 512 MiB and
1% of total RAM. Unknown readings do not trigger cancellation.

**Cancel** enters a stopping state while the runner terminates the process group
and verifies cleanup of that job's labelled Docker containers. A new run is held
until cleanup is confirmed. If cleanup cannot be verified, Jobs explains the
interruption and offers **Retry cleanup**. Work directories remain available for
resume. Job records persist across backend restarts; interrupted jobs are
reconciled conservatively before another run can start.

## Output layout

```text
project/
├── input_manifest/project_manifest.json
├── configuration/
├── work/
├── results/
│   ├── qc/{raw,clean}/
│   ├── trimmed/
│   ├── counts/kallisto/
│   ├── differential_expression/{mRNA,lncRNA}/<comparison_id>/
│   ├── figures/{mRNA,lncRNA,summary}/
│   └── tables/{mRNA,lncRNA,summary}/
├── reports/{execution_report.html,timeline.html}
└── logs/
```

The source-to-alias mapping is outside this project browser at
`MissusTomDemo/provenance/source_map.json`.

## Repository map

```text
MissusTom/
├── backend/       FastAPI API, validation, controlled runner, and tests
├── desktop/       React, TypeScript, Vite, and Tauri 2
├── docs/          Baseline inventory and architecture notes
├── schemas/       Versioned project-manifest schema
├── scripts/       Development and demo-preparation utilities
└── workflows/     Nextflow DSL2 workflow and pinned profiles
```

## Troubleshooting

- **Port 8000 is already in use** — stop the previous backend with `Ctrl+C`,
  then start `dev-backend.sh` again.
- **Docker is unavailable to the backend** — start it with
  `sg docker -c './scripts/dev-backend.sh'`, or sign out and back in so the new
  Docker group membership applies.
- **Load human demo returns unavailable** — confirm
  `/mnt/20TB_A/Adam/MissusTomDemo/project/input_manifest/project_manifest.json`
  exists and is readable.
- **A run fails** — inspect the job log in the Jobs view. Nextflow task details
  remain under the project `work/` directory for a resumable rerun.
- **A run is interrupted or cleanup is pending** — read the explanation in Jobs.
  Restore Docker access if necessary, then use **Retry cleanup** before starting
  another run. Only containers bearing that run's identifier are cleaned up.
- **A resource check blocks launch** — reduce the workflow CPU/RAM budget, close
  other memory-heavy applications, or choose an output filesystem with sufficient
  free space. Existing work and results are never deleted to make room.
- **The analysis image is missing** — run
  `sg docker -c './scripts/build-analysis-image.sh'` from the project root.
- **The GUI reports that the backend is unavailable** — confirm
  `curl http://127.0.0.1:8000/health` returns JSON.

## Current limits

- Scientific execution currently supports human paired-end reads, supplied
  kallisto indexes, Docker, and unpaired two-group DESeq2 designs. Single-end,
  non-human, batch/covariate models, and index construction remain unsupported.
- Results show the current project output directory; reruns share that directory
  rather than creating immutable snapshots for each job.
- Settings are local to this desktop profile. They apply to new projects; saved
  project manifests keep their chosen settings.
- The backend still runs as a separate development process rather than a
  packaged Tauri sidecar.
