# ONT human and mouse modBAM analysis

Supported species/build pairs are listed in the pipeline's
[start guide](../../../workflows/ont_analysis/START_HERE.md#species-and-references).
The app and standalone runner share reference-profile and FASTA-index checks.
Stage 05 uses the selected reference's main chromosome names and order, retaining
human chromosomes 20–22 and recording species/build in configuration and reports.
Synthetic workflow tests can use `ONT_TEST_RSCRIPT=/path/to/managed/bin/Rscript`
to exercise plotting and chromosome-selection checks with the installed ONT R
packages; those checks skip when the required R packages are unavailable.

Coverage and methylation window sizes are editable, but must match: exploration
joins their summaries by exact genomic coordinates. Canonical output filenames
retain the source workflow's `100kb` names even when another window size is used;
report headings describe configured windows.

This is the local, five-stage migration of the read-only ONT baseline:

1. checks primary-read modification tags, aligns each input modBAM and normalizes
   legacy Mm/Ml names in generated output while retaining tag values;
2. fully validates chunks, then coordinate-sorts and indexes one final BAM;
3. generates Mosdepth QC and exact run-length coverage products;
4. uses Modkit's high-depth-safe CpG pileup for the explicitly selected
   `5mc_only` or `5mc_5hmc` mode, preserving coverage-weighted summaries;
5. always writes core single-sample sequencing-QC and coverage-weighted
   methylation PDF figures, plot-data tables, and an HTML report; it adds the
   annotation-aware feature figure families when the complete optional
   annotation group is supplied.

See the [measurement contract](../../../workflows/ont_analysis/START_HERE.md#modified-base-measurements)
for legacy tag handling, missing MN tags, mode selection and unmeasured 5hmC.
The mode is stored in the manifest, generated configuration and report metadata.
Old manifests default to joint measurements. Validation rejects unknown modes.

Stage 03 includes wholly unaligned reference contigs at zero depth only when
BAM idxstats and complete zero-coverage windows corroborate the omission. Its
indexed per-base track and coverage tables include all FAI bases; partial tracks
still fail validation. Raw Mosdepth output is retained separately. See the
[coverage contract](../../../workflows/ont_analysis/START_HERE.md#zero-read-reference-contigs-and-coverage)
for the corrected outputs and audit metrics.

Run it only through the project manifest saved by Missus Tom:

```bash
python3 workflows/ont_analysis/run_pipeline.py \
  --manifest /project/input_manifest/project_manifest.json \
  --outdir /project/results --run-id local-run-001
```

Add `--check-only` to validate the manifest, contained input BAM paths,
references, local executables, and generated configuration without running
analysis (it does not require outputs from earlier stages). `--outdir` is the canonical results root: generated configuration is
stored at `results/samples/<sample-id>/config/`, and the stage directories are `01_alignment`
through `05_methylation_exploration`. `run-id` is recorded as provenance and
does not create another output nesting level.

The app's **Open output folder** button opens the results root when its project
QC overview is available, or `results/samples/` for older per-sample outputs.
The Results screen lists the project QC overview, ONT figures/reports,
methylation calls/summaries, sequencing coverage, and alignment files. Each
sample's PDFs are in `05_methylation_exploration/figures/`, alongside its HTML
report and plotting tables. New projects create the shared `samples/` and
`reference/` directories rather than empty top-level stage folders. Historical
single-sample outputs remain discoverable in their original layout.

Core Stage 05 reports include alignment-input yield/length statistics, coverage
breadth/depth, modification-call accounting, embedded browser previews, PDF
downloads, input checksums and measurement-scope notes. Main chromosomes are
plotted in readable panels; additional contigs remain in supporting tables.
Coverage plots use an explicitly labeled square-root depth axis. Unmeasured
5hmC and empty denominators remain unavailable, never zero. Modkit's approximate
failed-processing events are shown separately from failed/filtered CpG calls;
the report does not infer rejection reasons or unique-read counts from them.

After all included samples finish, `results/project_qc/ont_project_qc_report.html`
and `sample_qc_summary.tsv` provide a descriptive overview with links to each
sample report. They do not infer biological groups or perform differential
methylation analysis.

To refresh reports from existing Stage 03/04 outputs without alignment or
methylation calling, use the same manifest and results root with:

```bash
backend/.venv/bin/python workflows/ont_analysis/run_pipeline.py \
  --manifest /path/to/project/input_manifest/project_manifest.json \
  --outdir /path/to/project/results --run-id report-refresh --reports-only
```

This mode uses the saved per-sample configurations, takes the project's run
lock, and refuses concurrent execution for that project. Previous Stage 05
reports are archived under each sample's `tmp/stale_stage05/`; scientific
Stage 01–04 outputs and saved configuration are not regenerated. Use the
managed ONT environment when invoking the runner directly.

The runner consumes the standard ProjectManifest (`schema_version: "1.0.0"`),
requires at least one included sample and no filename-derived biology, and takes
each sample's ONT BAM list from its `ont_bam_files`. Samples run independently
under `results/samples/<sample-id>/`. Each resolved BAM must be
a regular `.bam` below `input_directory`; duplicate resolved paths and duplicate
basenames are refused. Required `reference_resources` are only `reference_fasta`,
`reference_fai`. `minimap2_index` is optional: without it, Stage 01 builds one
shared `results/reference/reference.lr-hq.mmi` using `minimap2 -x lr:hq -d` and
reuses it when its reference/tool/index fingerprints match. Its adjacent JSON
records build provenance and content hashes. Supplied indexes must be readable,
nonempty and built from the same FASTA with `lr:hq`; invalid explicit paths
are rejected. Indexing happens during execution, never during preflight or
`--check-only`. The four feature resources
`gencode_gff3`, `cpg_islands`, `ccre_table`, and `intergenic_bed` are optional,
but must be supplied together: without them Stage 05 writes its core
QC/methylation report, while with them it also writes feature exploration and
feature plots. `ont_instrument_report` is optional provenance in either mode.
Every supplied optional path is validated as a readable regular file. The optional
`parameters.expected_pass_bam_count` must match the total assigned BAM count. Tools are
deliberately resolved from the local `PATH`:
`dorado`, `samtools`, `mosdepth`, `modkit`, `bgzip`, `tabix`, and `Rscript`,
plus `minimap2` when building an index.
No tool, data, or baseline result is vendored.

The app's **Install required packages** action downloads a managed ONT tool/R
environment and supplies its executable paths when launching this runner. It
does not install into the backend virtual environment. Running this file directly
from a terminal still requires a suitable `PATH` and R environment; the app
handles environment selection automatically.

The app no longer uses system-installed pipeline tools or user R/Python
libraries as substitutes for this environment. Dorado's reviewed cuDNN aliases
are rewritten to the regular versioned libraries supplied inside its own archive;
no `/etc/alternatives` target is read or used. Unknown external links are rejected.

The reviewed baseline used Dorado 2.1.2, Minimap2 2.31 (to create the supplied
`minimap2_index`), Modkit 0.6.4, and Mosdepth 0.3.14. These are source-pinned
provenance targets, not installation instructions: the runner resolves local
executables from `PATH`. The annotation-aware Stage 05 R implementation requires
`data.table`, `ggplot2`, `ggrepel`, `scales`, `patchwork`, `GenomicRanges`,
`IRanges`, `GenomeInfoDb`, `rtracklayer`, and `jsonlite` in the R environment
selected by `Rscript`.

`cpg_islands` is the source CpG-island JSON asset consumed by the migrated R
analysis, not a generic BED substitute. `ccre_table` is the source cCRE CSV;
`gencode_gff3` and `intergenic_bed` retain their corresponding annotation
formats. An `ont_instrument_report`, if supplied, is retained as provenance;
its absence does not prevent core analysis or feature exploration.

Stages are sequential and runner subprocesses use fixed argument arrays with
`shell=False`. Completion markers are written last; valid current outputs are
reused and stale partial stage directories are moved beneath `results/tmp/`
instead of being deleted. The Stage 03 baseline's malformed `cd #!/usr/bin/env
bash` shebang is fixed in its vendored stage.

Scientific limits: this is a single-sample workflow. The exploration stage does
not perform correlation, PCA, DMR testing, or enrichment. Its annotation files
are recorded as provenance; scientific suitability of tool versions, Modkit
options, annotations, and interpretation still requires expert review.
`--check-only` validates local contract prerequisites only; it does not claim
scientific equivalence, execute a pileup, or verify biological outputs.

The managed runtime overlays the locked Modkit 0.6.4 package with the pinned
ambiguity repair from upstream PR #714. This prevents reverse-read ambiguity
panics and retains valid calls after ambiguous observations. Ambiguous query
positions receive no invented A/C/G/T identity. It does not add support for
fundamental-base N/U modification groups or reference-equality `SEQ =`.
The runtime verifies the repair's source identity and binary checksum before
execution, and records both in run provenance. Stock/older installations must
be reinstalled through Setup. Development builds first run
`backend/.venv/bin/python scripts/build-modkit-repair.py` (Rust 1.98.0, a C build
toolchain, libclang and the usual HTS compression/SSL development libraries are
build prerequisites). Packaged sidecar builds perform this step automatically;
operators do not need a compiler.

Modkit statistics may omit reference contigs with no bedMethyl rows. Stage 04
accepts those omissions only after scanning and validating the complete pileup.
Reference-wide summaries retain those contigs and their reference CpG counts,
with zero observed calls and `NA` rates when the valid-call denominator is zero.
A missing stats row for any contig that has a bedMethyl coordinate still fails,
even if that coordinate has zero valid calls.
