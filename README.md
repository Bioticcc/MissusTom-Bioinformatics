# Missus Tom

Missus Tom is a local desktop workbench for setting up, checking, and running
selected bioinformatics workflows. Your project files stay on your computer;
the application does not upload biological data.

## Availability

Linux x86_64 on Ubuntu and Debian is the only supported release target.
Successful tagged releases provide one ZIP containing the Debian `.deb`
installer, its checksum file, and installation instructions. Windows, macOS,
ARM Linux, and AppImage releases are unavailable.

Clean-machine GUI installation has not yet been verified.

## Available pipelines

- **Paired-end Bulk RNA-seq** prepares compatible transcriptome references and
  runs quality checks, trimming, transcript quantification, and manifest-defined
  two-group differential-expression analysis.
- **One-sample mouse ONT modified-base analysis** works with existing mouse
  pass modBAM files, retaining modified-base calls for alignment, coverage, and
  descriptive 5mC/5hmC exploration.

The pipelines are deliberately separate. Bulk RNA-seq does not currently
support single-end data, batch/covariate statistical models, or automatic
reference downloads. ONT currently supports one mouse GRCm38p6 sample only;
it does not re-basecall reads or provide multi-sample comparisons, DMR/DhMR,
enrichment, or human ONT analysis.

## Setup and demo fixtures

On first launch, open **Setup** and select Bulk RNA-seq, ONT analysis, or both.
Setup can prepare dependencies and/or a synthetic demo fixture for each selected
pipeline independently. You can return later to set up the other pipeline.

The synthetic demo fixtures are lightweight and contain no biological data. They
are for **functional workflow validation only**, not biological or clinical
interpretation. From the Dashboard, **Run Bulk RNA-seq Demo** prepares the bulk
fixture locally (when needed) and opens it for a controlled local-profile run
once Bulk managed dependencies are installed. The ONT synthetic fixture remains
a non-executable UI placeholder.

Bulk RNA-seq normally starts from raw paired reads plus a transcriptome FASTA
and matching GTF. Missus Tom validates transcript identifiers, creates or
reuses a managed Kallisto index, derives transcript-to-gene metadata, and runs:
paired FASTQ → raw QC → Cutadapt → clean QC → Kallisto → tximport/DESeq2.
An advanced path accepts an existing compatible Kallisto index, and
analysis-only mode accepts existing per-sample `abundance.tsv` files plus
compatible annotation. BioMart queries and manually prepared human BioMart
tables are not part of the normal workflow. The application does not download
project inputs or reference genomes.

The managed ONT installer downloads the reviewed official Dorado 2.1.2 archive
and verifies its pinned SHA-256 before extraction. Existing managed environments
remain isolated from new installations.

## Install a Linux release

For a successful tagged release, download and extract
`ver<version>_Linux-x86_64_Ubuntu-Debian.zip` from the project's GitHub Releases
page. The ZIP contains exactly one `.deb` installer, `SHA256SUMS`, and
`installation.md`. Keep the installer filename unchanged so checksum
verification can find it.

```bash
sha256sum --check SHA256SUMS
sudo apt install ./missus-tom_<version>_linux-x86_64.deb
```

Open **Setup**, choose the pipeline or pipelines you need, review any missing
requirements, then choose package installation where it is offered. Setup
downloads managed native tools over the internet. Bulk RNA-seq installation
uses an application-managed Micromamba environment with pinned Nextflow,
Java, FastQC, MultiQC, Cutadapt, and Kallisto versions, plus R with DESeq2,
tximport, and ggplot2 resolved from conda-forge/bioconda at install time.
Docker Engine is not part of that install and is not required for normal
local-profile runs; it remains optional for the Docker regression profile
only. The app does not run `sudo`, install GPU drivers, or download biological
data and references. After a successful install, local-profile runs can
proceed offline when the project's reference files are already on the machine.

## Use the app

1. Open **Setup** and prepare one or both pipeline environments.
2. Try **Run Bulk RNA-seq Demo** on the Dashboard for a quick synthetic bulk
   smoke path, or select **New project → Bulk RNA-seq** and scan a paired-FASTQ
   directory.
3. Confirm sample pairings and biological conditions, choose matching
   transcriptome FASTA/GTF references, select strandedness and trimming
   settings, and define numerator-versus-denominator comparisons.
4. Validate and save the project, then review the run plan. Reference
   preparation occurs through the same normal local run path.
5. Select **Run pipeline** and follow preparation and workflow progress in
   **Jobs**.
6. Open **Results** to inspect QC, trimmed reads, Kallisto output, normalized
   expression, differential-expression tables/figures, logs, and provenance.

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
- Normal bulk runs use the local Nextflow profile and managed native tools.
  The Docker profile is retained for regression.
- The generic reference/statistical path is covered with synthetic
  transcript/gene identifiers; support for every organism or annotation
  convention is not claimed. FASTA and GTF files must represent the same
  transcript annotation release.
- Differential expression is limited to independent biological samples with
  `~ condition` and explicit pairwise contrasts. Batch, paired-patient,
  longitudinal, and interaction designs are not modeled.
- An existing Kallisto index cannot prove its own annotation compatibility.
  Supply its original transcriptome FASTA when available so Missus Tom can
  validate identifiers; otherwise compatibility remains user-supplied.
- Synthetic fixtures validate pipeline wiring only; they do not establish
  scientific validity. The ONT synthetic bundle cannot run the ONT workflow.
- WSL2 Ubuntu uses the normal Linux/native execution path and does not require
  Docker Desktop. Projects under the Linux filesystem generally perform better
  than heavy I/O under `/mnt/c`; this is guidance, not a hard block. Preflight
  storage warnings remain authoritative because Linux-reported virtual free
  space may not reflect Windows host capacity.
- Clean-machine GUI installation remains unverified. Clean-machine internet
  installation of the managed tools, and scientific equivalence of native-tool
  versus Docker-profile results, have not been verified.
