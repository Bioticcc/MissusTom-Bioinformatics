# ONT mouse modBAM analysis

Coverage and methylation window sizes are editable, but must match: exploration
joins their summaries by exact genomic coordinates. Canonical output filenames
retain the source workflow's `100kb` names even when another window size is used;
report headings describe configured windows.

This is the local, five-stage migration of the read-only ONT baseline:

1. aligns each input modBAM while checking MM/ML/MN tag retention;
2. fully validates chunks, then coordinate-sorts and indexes one final BAM;
3. generates Mosdepth QC and exact run-length coverage products;
4. uses Modkit's high-depth-safe CpG pileup, preserving separate 5mC and 5hmC records and coverage-weighted summaries;
5. always writes core single-sample sequencing-QC and coverage-weighted
   methylation PDF figures, plot-data tables, and an HTML report; it adds the
   annotation-aware feature figure families when the complete optional
   annotation group is supplied.

Run it only through the project manifest saved by Missus Tom:

```bash
python3 workflows/ont_analysis/run_pipeline.py \
  --manifest /project/input_manifest/project_manifest.json \
  --outdir /project/results --run-id local-run-001
```

Add `--check-only` to validate the manifest, contained input BAM paths,
references, local executables, and generated configuration without running
analysis (it does not require outputs from earlier stages). `--outdir` is the canonical results root: generated configuration is
stored at `results/config/`, and the stage directories are `01_alignment`
through `05_methylation_exploration`. `run-id` is recorded as provenance and
does not create another output nesting level.

The runner consumes the standard ProjectManifest (`schema_version: "1.0.0"`),
requires exactly one included sample and no filename-derived biology, and takes
the ONT BAM list from that sample's `ont_bam_files`. Each resolved BAM must be
a regular `.bam` below `input_directory`; duplicate resolved paths and duplicate
basenames are refused. Required `reference_resources` are only `reference_fasta`,
`reference_fai`, and `minimap2_index`. The four feature resources
`gencode_gff3`, `cpg_islands`, `ccre_table`, and `intergenic_bed` are optional,
but must be supplied together: without them Stage 05 writes its core
QC/methylation report, while with them it also writes feature exploration and
feature plots. `ont_instrument_report` is optional provenance in either mode.
Every supplied optional path is validated as a readable regular file. The optional
`parameters.expected_pass_bam_count` must match the assigned BAM list. Tools are
deliberately resolved from the local `PATH`:
`dorado`, `samtools`, `mosdepth`, `modkit`, `bgzip`, `tabix`, and `Rscript`.
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

The reviewed baseline used Dorado 2.0.0, Minimap2 2.31 (to create the supplied
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
