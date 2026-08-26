# Missus Tom

Missus Tom is a local Yan Lab desktop application for bulk RNA-seq project
configuration, validation, and controlled workflow execution.

Version 0.3.0 includes an eight-sample human-data demo. The enabled workflow runs:

1. FastQC and MultiQC on raw paired reads.
2. Cutadapt with the observed Yan Lab paired-end settings: Q20, minimum length
   20, and the existing TruSeq adapter sequences.
3. FastQC and MultiQC on trimmed reads.
4. Kallisto 0.51.1 with the existing GENCODE v49 index and `--rf-stranded`.
5. Transcript-to-gene import for protein-coding and lncRNA gene classes.
6. DESeq2 differential expression for OD1 versus H using four biological
   replicates per condition.
7. Normalized matrices, differential-expression tables, and the diagnostic
   plots used by the original human analysis scripts.

Enrichment and biological interpretation are not enabled. The existing
`../BulkRnaSeq` scientific baseline remains separate and read-only.

## Demo data boundary

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
MultiQC 1.33, Cutadapt 5.2, and Kallisto 0.51.1. Differential expression uses
the project-local `missus-tom/rnaseq-analysis:0.3.0` image built from the
digest-pinned Bioconductor 3.21 / R 4.5.2 base.

Build the analysis image once before running the full demo:

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

In the application:

1. Select **Load human demo**.
2. Review the eight-stage run plan and selected-folder previews.
3. Select **Run pipeline**.
4. Use **Jobs** for status and logs.
5. Use **Results** for files written by the workflow.

Runs use the persistent Nextflow work directory under the demo project and
start with `-resume`. Completed tasks are reused. Missus Tom does not delete
work directories or results.

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

## Execution controls

The backend launches an argument array with `shell=False`; it does not accept a
command from the GUI. Before starting, it checks all of the following:

- Execution was explicitly enabled by the local launcher.
- Output is exactly under the configured demo root.
- The submitted manifest matches the saved manifest.
- The eight expected pseudonymous samples are present, with four H and four OD1.
- FASTQs are regular files in the restricted demo input directory.
- Organism, layout, strandedness, adapters, trim settings, and read count match
  the approved demo contract.
- The only comparison is OD1 versus H and differential expression is enabled.
- Docker and Nextflow are available to the backend process.

Only files inside the configured project output are indexed. Symlinks and files
outside the project root are excluded.

## Output layout

```text
MissusTomDemo/project/
├── input_manifest/project_manifest.json
├── configuration/
├── work/
├── results/
│   ├── qc/{raw,clean}/
│   ├── trimmed/
│   ├── counts/kallisto/
│   ├── differential_expression/{mRNA,lncRNA}/OD1_vs_H/
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
- **The analysis image is missing** — run
  `sg docker -c './scripts/build-analysis-image.sh'` from the project root.
- **The GUI reports that the backend is unavailable** — confirm
  `curl http://127.0.0.1:8000/health` returns JSON.

## Current limits

- Controlled execution is limited to the prepared eight-sample human demo and
  the OD1-versus-H comparison.
- Job records are held in backend memory while run-state JSON and all workflow
  logs/results persist on disk.
- Settings and recent-project loading remain placeholders.
- The backend still runs as a separate development process rather than a
  packaged Tauri sidecar.
