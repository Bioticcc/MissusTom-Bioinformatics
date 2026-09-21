# Missus Tom

Missus Tom is a local Yan Lab desktop application for project configuration,
validation, and controlled bioinformatics workflow execution. The workbench now
keeps two pipelines behind separate adapters so their species, inputs, tools,
and scientific assumptions do not leak into one another:

- **Bulk RNA-seq (human)** — paired short-read quantification and two-group
  differential expression.
- **ONT (Oxford Nanopore) Analysis (mouse)** — single-sample GRCm38p6 modified-
  BAM alignment, coverage QC, separate 5mC/5hmC summaries, and descriptive
  methylation exploration.

The bulk RNA-seq workflow accepts user-created human paired-end projects and the
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

The ONT workflow migrates the restartable five-stage contract from the read-only
`../ONTAnalysis` project. It consumes existing pass modBAMs so modified-base
`MM`, `ML`, and `MN` tags are retained; it does not repeat basecalling. Its
initial scope is one mouse sample, with no DMR/DhMR, enrichment, or differential
comparison. Reference and annotation files are selected explicitly instead of
using the source project's machine-specific paths.

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

### Setup and synthetic demo fixtures

The dedicated **Setup** screen lets an operator select Bulk RNA-seq, ONT
analysis, or both independently, then choose package installation and/or
synthetic demo preparation for each selection. Synthetic demo bundles are
generated locally under the application state directory (normally
`~/.local/share/missus-tom/demos/<pipeline>`), contain no biological data, and
include a machine-local manifest and self-consistency metadata. Their manifests
embed absolute paths, so regenerate a bundle on each machine instead of moving
it between machines. The recorded hashes detect accidental corruption or
inconsistent local files; they are not a trusted, tamper-proof integrity
mechanism.

These fixtures support setup and manifest/UI integration only. They are not
executable end-to-end workflows: their placeholder references and ONT `.bam`
file intentionally cannot support scientific or runtime validation. Clean-machine
installation and end-to-end execution of these fixtures have not yet been
validated. GitHub Linux releases launch the backend as an owned Tauri sidecar;
source development still uses a separate backend process.

## Install a GitHub Linux release

Download the Linux x86_64 `.AppImage` or `.deb` and `SHA256SUMS` from the
matching [GitHub Release](../../releases). Releases are currently Linux x86_64
only; macOS, Windows, ARM Linux, and human-only/mouse-only installers are not
provided.

Verify the downloaded package before installing it:

```bash
sha256sum --ignore-missing --check SHA256SUMS
```

To use the AppImage, make it executable and start it:

```bash
chmod +x missus-tom_<version>_linux-x86_64.AppImage
./missus-tom_<version>_linux-x86_64.AppImage
```

To install the Debian package:

```bash
sudo apt install ./missus-tom_<version>_linux-x86_64.deb
```

On the first launch, open **Setup**, choose the pipeline or pipelines to use,
and review missing host prerequisites before selecting package installation.
The application detects missing tools and explains the required operator action;
it never runs `sudo`, installs Docker Engine or GPU drivers, or downloads
reference genomes, annotations, basecalling models, or project inputs.

The GitHub release does not include the restricted human demo, any ONT data,
reference data, managed dependency environments, Docker images, project
results, logs, or runtime state. The app can prepare tiny synthetic fixtures,
but they are setup/manifest fixtures only and cannot be executed end-to-end.

## Source-development prerequisites

To develop from a source checkout, install:

- Linux
- Python 3.11 or newer
- Node.js 18 or newer and npm
- Rust/Cargo and the Linux Tauri 2 prerequisites

For **human bulk RNA-seq** execution:

- Java 17 or newer
- Nextflow 24.04 or newer
- Docker Engine, with the current user permitted to access the daemon

For **mouse ONT** execution, the isolated tool/R environment requires Dorado,
minimap2, Samtools/BGZF/Tabix,
Mosdepth, Modkit, Python 3, and the R packages listed in
`workflows/ont_analysis/README.md`. Large mouse reference/data files remain
operator-supplied, not downloaded with the packages.
ONT execution does not require Nextflow or the bulk RNA-seq Docker images.
Managed ONT installation is currently fail-closed until an authoritative Dorado
2.0.0 archive SHA-256 digest is reviewed and pinned. Existing verified managed
environments remain detectable, but a release user cannot initiate a new ONT
dependency installation yet. Pipeline runtime dependencies remain separate.

### Install pipeline packages from the app

Each selected pipeline's dependency card in **Setup**, the project wizard, or
the run-plan screen lists missing executables, R libraries, or container images.
Click **Install required packages** to start a background installation; progress
and failures appear in the card. You can skip a pipeline and install it later
from Setup, the project wizard, or the run-plan screen.
The ONT card currently reports its checksum gate as a manual blocker rather than
downloading an unverified executable archive.

Automatic installation initially supports Linux x86_64. It uses a private
environment under the application state directory (normally
`~/.local/share/missus-tom/dependencies`), not your backend `.venv` or system R.
No terminal environment activation is needed: validation and runs resolve these
tools automatically. Pipeline executables and R libraries must come from the
managed environment: existing system installations do not satisfy these checks.
Once the authoritative digest is pinned, Dorado's known cuDNN host aliases are
replaced with relative links to bundled versioned libraries; the installer never
reads those host targets. Unknown external archive links remain rejected.
The installer does not run `sudo`, install Docker Engine/GPU drivers, or download
reference genomes, annotations, basecalling models, or project inputs.

Installation needs internet access and sufficient free disk space; large R
environments and container images can take substantial time. Keep the backend
running until installation finishes. Installation and analysis are mutually
exclusive to avoid changing dependencies during a run. Downloads contact
software repositories only; no biological data is uploaded. Third-party
software remains subject to its own licensing terms.

The bootstrap uses [Micromamba's official releases](https://github.com/mamba-org/micromamba-releases)
and [Bioconda](https://bioconda.github.io/) / conda-forge packages. The disabled
Dorado step is intended to use the upstream distribution linked by its
[official project](https://github.com/nanoporetech/dorado) only after checksum
verification is enforced.

The workflow uses digest-pinned public BioContainers images for FastQC 0.12.1,
MultiQC 1.33, Cutadapt 5.2, and Kallisto 0.52.0. Differential expression uses
the project-local `missus-tom/rnaseq-analysis:0.3.0` image built from the
digest-pinned Bioconductor 3.21 / R 4.5.2 base.

The bulk dependency installer downloads Java/Nextflow and prepares its workflow
images, including building the analysis image. Docker Engine must already be
installed, running, and accessible to the backend user. For manual setup, build
the bulk RNA-seq analysis image once before running that workflow:

```bash
sg docker -c './scripts/build-analysis-image.sh'
```

## Start the application

Startup commands are unchanged. Restart the backend and desktop after updating
the source. Pipeline package installation is available from Setup, the selected
pipeline's project wizard, and the run-plan screen; it is not needed just to
open the app.

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

For a user project, select **New project**, choose the pipeline, and then provide
that pipeline's inputs. Bulk FASTQ mode discovers paired reads and
requires a kallisto index plus BioMart. Analysis-only mode discovers one
Kallisto `abundance.tsv` per sample and requires BioMart, but not FASTQs or an
index. Review the biological design, add comparisons, validate, save, and run.
The design step can import the original human patient CSV, including `SampleID`,
`Condition`, `Batch`, `Patient`, and `Intervention`. Unsaved wizard settings can
also be exported and imported as JSON for debugging or continuation.

ONT mode accepts explicitly selected pass modBAM files and fixes the initial
scientific scope to `Mus musculus` / `GRCm38p6`. Select the reference FASTA and
FAI and matching minimap2 index. No existing figures or HTML report are required.
GENCODE GFF3, CpG-island, cCRE, and intergenic annotations are an optional complete
set for annotation-based exploration; leave all four empty for core analysis.
An instrument-report HTML can optionally be retained as sequencing provenance.
The ONT wizard intentionally omits experimental-group and comparison steps.

Use **Recent projects** on the dashboard to reopen a saved project, or **Open
project** to select its `input_manifest/project_manifest.json`. Missing inputs
are reported during validation without rewriting the saved manifest. **Settings**
saves the project parent folder and total CPU/RAM defaults locally for new projects.

On the run-plan screen:

1. Review the eight-stage run plan and selected-folder previews.
2. Choose **Resume previous run** to reuse completed tasks or **Start from
   beginning** to execute every task again.
3. For bulk RNA-seq, confirm **Quantification + analysis** for the complete FASTQ workflow or
   **Analysis only** to use discovered abundance tables or reuse complete
   kallisto outputs from this project. ONT runs its five restartable stages from
   the saved manifest.
4. Select **Run pipeline**.
5. Use **Jobs** for status and logs.
6. Use **Results** for files written by the workflow.

Active run logs receive a timestamped heartbeat every 30 minutes. Successful
runs end with an explicit UTC `Completed at` timestamp.

Minimizing the desktop app during an active run opens a small, always-on-top
status overlay at the bottom left of the screen. It shows the project name,
start time, reported pipeline stage, and latest log message. Drag its header to
move it, or select **Open app** to restore the main window. The overlay hides
when the main window is restored or the run is no longer active.

Bulk RNA-seq runs use the persistent Nextflow work directory under the project. Resume targets
a recorded Nextflow session from the same project, preferring the same start
stage. With no eligible session, the run starts without a resume target. Older
projects can recover their session name from local logs. The start-from-beginning
option omits `-resume`, so completed tasks are not reused. Neither option deletes
existing work directories, results, or logs. Workflow code changes can invalidate
affected cached tasks even when resuming.

ONT runs use their own completion and input-validation markers instead of
Nextflow sessions. The run-plan screen always performs a restartable run; it
does not expose a forced rebuild. Existing ONT results are never deleted to
make room or restart a stage.

## Development setup

Create the project-local backend environment:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Build Linux sidecars with the separately installed packaging tools:

```bash
cd ..
backend/.venv/bin/python -m pip install -e 'backend[packaging]'
bash scripts/build-linux-sidecars.sh x86_64-unknown-linux-gnu
```

This stages `workflows/` and `scripts/build-analysis-image.sh` under
`backend/build/sidecar-resources`, then writes
`missus-tom-backend-x86_64-unknown-linux-gnu` and
`ont-analysis-runner-x86_64-unknown-linux-gnu` to `desktop/src-tauri/binaries/`.
The release configuration adds these sidecars and workflow resources; the base
Tauri configuration remains development-safe without external binaries.

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
command from the GUI. Both adapters require the execution kill switch, a saved
matching manifest, safe paths, and available workstation resources. Before
starting bulk RNA-seq, it additionally checks:

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

ONT has separate gates: exactly one included mouse GRCm38p6 sample, no
comparisons, an explicit non-colliding pass-BAM chunk set, readable mouse
alignment references and all required local tools. Annotation exploration is
optional; supplied annotation sets must be complete and readable. An instrument
report is optional provenance, not an analysis prerequisite.
Its native tools run from the reviewed managed environment, not Docker. The
ONT CPU/RAM profile is an admission and monitoring budget, not a hard per-tool
memory limit: native subprocesses are not placed in a Docker/cgroup memory
ceiling.

Managed package isolation is not a filesystem sandbox: normal OS utilities,
the system loader/base libraries, and applicable GPU drivers or Docker Engine
remain system prerequisites. User-confirmed input/reference paths are unaffected.

### Keeping the workstation responsive

CPU and memory settings are budgets for the **whole workflow**. The parallel-task
setting limits concurrent tasks across all bulk RNA-seq stages. Each Docker task also has
hard CPU and memory limits and cannot expand into additional host swap. The
Nextflow JVM has a 1 GiB heap cap; analysis thread pools are bounded.

Before launch, the backend reserves 10% of logical CPUs (at least one, except on
a single-CPU host) and the greater of 2 GiB or 10% of total RAM for the desktop
and control processes. It checks the output filesystem against a conservative
estimate of four times the FASTQ input size plus 10 GiB, or twice the abundance
table size plus 10 GiB for analysis-only runs. These are capacity estimates, not
predictions of final output size. ONT uses the same four-times-input-plus-10-GiB
capacity estimate, calculated from its selected BAM chunks. Resource warnings
allow project setup; unsafe resource requests block execution. Single-lane
inputs go directly to Cutadapt,
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

ONT projects use pipeline-specific result directories:

```text
project/
├── input_manifest/project_manifest.json
├── work/
├── results/
│   ├── 00_manifests/
│   ├── 01_alignment/
│   ├── 02_alignment_qc/
│   ├── 03_ont_qc_coverage/
│   ├── 04_methylation/
│   └── 05_methylation_exploration/
└── logs/
```

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

- Bulk RNA-seq execution currently supports human paired-end reads, supplied
  kallisto indexes, Docker, and unpaired two-group DESeq2 designs. Its single-end,
  non-human, batch/covariate models, and index construction remain unsupported.
- ONT execution initially supports one mouse GRCm38p6 sample from existing pass
  modBAMs. Re-basecalling, multi-sample differential methylation, DMR/DhMR,
  enrichment, and human ONT references remain unsupported.
- Results show the current project output directory; reruns share that directory
  rather than creating immutable snapshots for each job.
- Settings are local to this desktop profile. They apply to new projects; saved
  project manifests keep their chosen settings.
- Source development uses a separate backend process. Linux release packages
  launch an owned backend sidecar on a dedicated loopback port. Closing the
  window stops it only when no run or dependency installation is active;
  otherwise the window hides and the sidecar remains alive.
