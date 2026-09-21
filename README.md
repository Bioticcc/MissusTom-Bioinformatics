# Missus Tom

Missus Tom is a local desktop workbench for setting up, checking, and running
selected bioinformatics workflows. Your project files stay on your computer;
the application does not upload biological data.

## Availability

Linux x86_64 is the only supported release target. Successful tagged releases
provide an AppImage and a Debian `.deb` package. Windows, macOS, and ARM Linux
are unavailable.

Clean-machine GUI installation has not yet been verified.

## Available pipelines

- **Human paired-end Bulk RNA-seq** prepares and runs quality checks, trimming,
  transcript quantification, and two-group differential-expression analysis for
  human paired-end data.
- **One-sample mouse ONT modified-base analysis** works with existing mouse
  pass modBAM files, retaining modified-base calls for alignment, coverage, and
  descriptive 5mC/5hmC exploration.

The pipelines are deliberately separate. Bulk RNA-seq does not currently
support single-end data, non-human projects, index construction, or
batch/covariate models. ONT currently supports one mouse GRCm38p6 sample only;
it does not re-basecall reads or provide multi-sample comparisons, DMR/DhMR,
enrichment, or human ONT analysis.

## Setup and demo fixtures

On first launch, open **Setup** and select Bulk RNA-seq, ONT analysis, or both.
Setup can prepare dependencies and/or a synthetic demo fixture for each selected
pipeline independently. You can return later to set up the other pipeline.

The synthetic demo fixtures are lightweight setup and UI fixtures only. They do
not contain biological data, and they are **not executable end-to-end today**:
their placeholder inputs and references cannot validate or run a scientific
workflow.

Bulk RNA-seq can start from raw paired reads, which require a compatible
kallisto index, or from compatible existing per-sample `abundance.tsv`
quantifications in analysis-only mode. Both routes require the needed
annotation/BioMart data and host software. ONT requires locally supplied pass
modBAM files and mouse reference resources. The application does not download
project inputs or reference genomes.

The managed ONT installer is intentionally blocked: an authoritative SHA-256
checksum for the Dorado 2.0.0 archive still needs review and pinning. Existing
verified managed environments can be detected, but a new managed ONT dependency
installation cannot begin until that checksum is available.

## Install a Linux release

For a successful tagged release, download the matching AppImage or `.deb` and
its `SHA256SUMS` file from the project's GitHub Releases page. Keep the
package's release filename unchanged so checksum verification can find it.

```bash
sha256sum --ignore-missing --check SHA256SUMS
```

For an AppImage:

```bash
chmod +x <downloaded-appimage>.AppImage
./<downloaded-appimage>.AppImage
```

For a Debian package:

```bash
sudo apt install ./<downloaded-package>.deb
```

Open **Setup**, choose the pipeline or pipelines you need, review any missing
requirements, then choose package installation where it is offered. The app
does not run `sudo`, install GPU drivers or Docker Engine, or download biological
data and references.

## Use the app

1. Open **Setup** and prepare one or both pipeline environments.
2. Select **New project**, choose a pipeline, and provide its inputs and
   required reference files.
3. Confirm the project details, save the project, and review the run plan.
4. Select **Run pipeline** and follow progress in **Jobs**.
5. Open **Results** to see files produced for that project.

Use **Recent projects** to reopen a saved project. Bulk RNA-seq projects define
the two groups to compare. ONT projects select one mouse sample and do not
include an experimental-comparison step.

## Develop from source

Source development needs Linux, Python 3.11+, Node.js 18+ with npm, Rust/Cargo,
and the Linux prerequisites for Tauri 2. Workflow execution has additional
requirements; see the technical documentation below.

```bash
git clone <repository-url> MissusTom-Bioinformatics
cd MissusTom-Bioinformatics

python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -e 'backend[dev]'

cd desktop
npm install
```

Start the backend from the repository root in one terminal:

```bash
./scripts/dev-backend.sh
```

Start the desktop application from `desktop/` in another terminal:

```bash
npm run tauri dev
```

## Technical details

For development checks, packaging guidance, and validation commands, see
[the workflow guide](docs/agent/WORKFLOWS.md). For the application's component
boundaries and local-security design, see [the architecture
overview](docs/mvp_architecture.md).

## Current limits

- This is local-only software; data, reference files, results, logs, and
  runtime state are not included in releases.
- Synthetic fixtures do not establish workflow readiness, end-to-end execution,
  or scientific validity.
- Clean-machine GUI installation remains unverified.
