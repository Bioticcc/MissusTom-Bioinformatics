# SingleCell RNA-seq foundation

## Pending input change — 2026-10-30

User decision: SingleCell analysis should accept an existing **Seurat object
saved as `.rds`**, not FASTQ files. This supersedes the earlier FASTQ-input
requirement below. **Record only for now; do not implement this change yet.**

When resumed, update the desktop input screen, manifest, validation, analysis
entry point and setup requirements together. Define required assays/layers and
sample metadata, and how to handle objects already processed in Seurat, before
deciding which analysis steps to repeat. Preserve the original input object.

## Current implementation and history

Previous scope: begin a FASTQ-to-analysis workflow derived from HBC's Intro-to-scRNAseq,
using Bulk's Nextflow/R/source-documentation conventions. Existing ONT, Bulk,
wizard, and git_push edits belong to other work and must be preserved.

Implemented first increment: standalone, versioned input contract; strict preflight;
filtered 10x v3 sparse matrices; per-sample explicit QC; unintegrated Seurat v5
normalization/PCA/clustering/UMAP and exploratory cluster markers; provenance;
candidate native environment and lock-generation instructions; synthetic tests.
No species, group, donor, reference, or mitochondrial genes inferred from names.

Validation completed: 16 tests passed, including actual Matrix sparse import/QC,
count rejection, run-directory preservation, output-completeness rejection, and
real one/two-sample Nextflow staging with a replacement R command. One opt-in full
Seurat test was skipped. Python lint/format, all R parses, Bash syntax, JSON syntax
and Nextflow local config passed. Staging/config used cached Nextflow 26.04.6;
candidate environment pins Bulk's 24.04.4, still requiring validation in that env.

Full scientific smoke requires a separate Seurat environment: the host has
R 4.2.2 / Matrix 1.5.3 and lacks Seurat, SeuratObject and future. The dependency
checker correctly rejects it. No packages were installed, no lock was fabricated,
and no user scientific data was analyzed. A real two-sample Seurat test is available
with SINGLECELL_TEST_SEURAT=1 once the environment is installed. Do not install
into Bulk/ONT environments. Setup specification is a candidate until resolved.

Remaining product gates: resolved explicit environment lock and isolated install;
scientific fixture execution; integration/doublet/ambient-RNA decisions; shared
manifest/schema/TypeScript, adapter, preflight, Setup, wizard, artifact discovery,
source revisions, containment, packaging, and native manual acceptance. Keep the
pipeline out of the application registry until those contracts are implemented.

## FASTQ requirement and selectable inputs

User clarified FASTQs are required immediately and chemistry is not yet known.
Chemistry and cells/nuclei are explicit selectable inputs; unknown blocks runs.
Current CLI/per-library manifest choices are implemented; desktop selector is
pending with the rest of the shared-contract/wizard work. `chemistries.json`
contains labels/descriptions, including unavailable v4/5-prime/Flex/other options.

Added `run_fastq.py` / `fastq.nf` / `bin/fastq_stage.py`: pinned STAR 2.7.11b index
generation, confirmed 10x 3-prime v2/v3 geometry, local whitelist, explicit paired
lanes, full read synchronization checks before mapping, EmptyDrops_CR cell calling,
explicit Gene/GeneFull mode, lossless matrix packaging, validated handoff to Seurat.
Outputs retain raw counts/mapping logs, commands and FASTQ/reference/source hashes.
The candidate environment and lock generator include STAR/gzip/native probes.
No runtime downloads; launchers receive NXF_OFFLINE=true as well as -offline.

FASTQ graph runs in the outer new run directory; count analysis runs under
`analysis/`. Explicit reports_dir prevents FASTQ reports escaping into the parent.
Real two-library/two-lane Nextflow graph and downstream handoff passed with
substitute STAR/R executables. These are orchestration checks, not scientific
acceptance. STAR is absent on the host. Full STAR+Seurat validation and installation
remain pending. FASTQ setup/selection details are in workflow `FASTQ_INPUTS.md`.

Final source validation after FASTQ/reference work: 26 tests passed, one complete
Seurat scientific test skipped. Python lint/format, Bash syntax, R parse, both
Nextflow graphs, JSON syntax and chemistry listing passed. Reference checks stream
FASTA/GTF and reject contig, coordinate, mitochondrial-ID and small-genome index
incompatibilities. Explicit reports_dir on BOTH runners keeps reports under each
run. Existing unrelated worktree edits remain untouched.

## Desktop discovery and configuration

SingleCell is now selectable under New project → Pipeline. Dedicated
`desktop/src/screens/SingleCellSetup.tsx` edits a standalone FASTQ manifest with
per-library chemistry (the actual shared JSON catalog), material/count mode,
multiple paired lanes, reference and mitochondrial IDs, QC and analysis settings.
Native file selection and JSON export work through existing native commands.
Incomplete/unknown drafts may be exported; no validation or execution is claimed.
The backend project schema/registry remain unchanged until execution integration.

Existing Bulk/ONT drafts and the SingleCell draft survive switching back and forth.
Setup and README identify the entry point and development limits. New mounted
React regression covers selection, chemistry, file selection, multiple lanes/
libraries, export shape, no run/save API requests, and both drafts' preservation.
All frontend tests, lint, TypeScript and build passed. A temporary loopback Vite
server verified the dev module and shared chemistry JSON load; it was stopped.
Native GUI/file-dialog acceptance remains [Awaiting manual testing].
