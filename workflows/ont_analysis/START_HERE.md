# Start here: ONT Analysis

This pipeline processes human or mouse Oxford Nanopore modBAM samples in
five ordered stages. It checks alignment, measures quality and coverage, and
summarizes DNA methylation. Each sample has its own isolated results directory
under `results/samples/<sample-id>/`; cross-sample statistical comparisons are
not yet part of this workflow.

## Species and references

Select the species and assembly explicitly. Human references are GRCh38/hg38
or GRCh37/hg19. Mouse references are GRCm38p6/GRCm38/mm10 or GRCm39/mm39.
Each project uses one species and assembly. Existing mouse projects keep their
settings; changing species or assembly in the wizard clears reference and
annotation paths so you can supply matching files.

Supply a reference FASTA and its FASTA index (`.fai`). A minimap2 index (`.mmi`)
is optional: Stage 01 generates one from that FASTA when omitted. An existing
supplied index must come from the same FASTA and use the `lr:hq` preset.
The FAI must include all autosomes (22 for human,
19 for mouse), using `chr1` or `1` naming. Sex and mitochondrial chromosomes
are included when present. Annotation files must use matching names and assembly.
The chromosome check does not prove the identity of the assembly or that the
FASTA, FAI, minimap2 index and annotations match; verify their source/version.

Optional feature exploration requires the complete GENCODE GFF3, UCSC
CpG-island JSON, cCRE table and intergenic BED group for the selected assembly.
Without that group, core coverage and methylation reports still run. BAMs must
retain modification tags and probabilities for either species. Modern `MM`/`ML`
and legacy `Mm`/`Ml` tags are accepted. Existing `MN` tags must match the read's
sequence length; an absent `MN` is allowed for primary mapped reads.

## Modified-base measurements

Choose **5mC and 5hmC** for joint calls or **5mC only** for a 5mC-only model in
ONT pipeline options. This is recorded as `parameters.modification_mode`:
`5mc_5hmc` (the backward-compatible default) or `5mc_only`. A model's available
measurements cannot be inferred from sample age or fabricated by alignment.

Stage 01 checks input tags before indexing/alignment, then normalizes legacy tag
names in its generated BAM stream without changing probabilities, modification
codes, implicit/explicit modes or records. It preserves existing `MN` values and
never invents missing ones. Original BAMs are not rewritten. Modkit performs the
full tag validation and uses primary alignments by default.

5mC-only runs write `cpg_5mc.bed.gz`; joint runs retain `cpg_5mc_5hmc.bed.gz`.
5mC-only summaries report 5hmC as `NA` / `not_measured`, not zero. The reported
total modified count includes only measured modifications. Core and optional
feature reports support both modes; 5hmC-only plots and cross-modification
comparisons are omitted when 5hmC was not measured. Changing the mode invalidates
affected stage outputs while preserving the reusable reference index.
The supported profiles are recorded in `reference_profiles.json`; the shared
checks are in `reference_contract.py`.

## Zero-read reference contigs and coverage

Mosdepth can omit wholly unaligned contigs from its per-base track and summary,
even while its window tables include them at zero depth. Stage 03 completes an
omitted contig only when BAM index statistics show zero mapped reads, BAM/FAI
lengths agree, and its complete window and threshold tables confirm zero coverage.
It continues to reject partial contigs, gaps, reordered intervals and inconsistent
totals. All FAI bases remain in coverage percentages and mean-depth denominators.

`per_base_coverage.bed.gz` and its CSI index contain the reference-complete track.
The original track/index are retained as `mosdepth.raw.per-base.bed.gz` and `.csi`.
Mosdepth summary/distribution files remain raw tool output and may omit unaligned
contigs; use `coverage_summary.tsv` and `chromosome_coverage.tsv` for corrected
metrics. Coverage summary audit rows list the added contigs, their bases and the
reference length represented by Mosdepth's original total row.

## Automatic alignment index

Stage 01 passes the `.mmi` to `dorado aligner` to align each input modBAM.
It is a saved search index of the reference genome, not an index of the input
BAMs. Later stages use the aligned BAM and reference FASTA/FAI.

When no `.mmi` is supplied, the pipeline runs minimap2 with `-x lr:hq -d`
using the configured alignment thread budget and publishes
`results/reference/reference.lr-hq.mmi`. All samples share it. No reference is
written beside the source FASTA, and validation/check-only does not build it.
`reference.lr-hq.mmi.json` records the FASTA/index SHA-256 hashes, file
fingerprints, minimap2 version and preset. Unchanged indexes are reused;
changed references, tools or generated index files trigger rebuilding. Failed
builds do not publish a completed index. The first run needs extra indexing
time and output disk space. A missing or empty explicitly supplied index is an
input error; omit that field to request automatic generation.

## How the files connect

1. `run_pipeline.py` is the main runner. It reads the project settings and runs
   each stage in order.
2. `stages/01_align_modbam.sh` prepares the aligned modified-base BAM data.
3. `stages/02_finalize_alignment.sh` checks and publishes the alignment files.
4. `stages/03_ont_qc_and_coverage.sh` creates quality and coverage summaries.
5. `stages/04_methylation_analysis.sh` creates methylation calls and core
   methylation summaries.
6. `stages/05_methylation_exploration.sh` creates the final exploration tables,
   figures, and reports.
7. Files under `lib/` are helpers used by those stages. Python helpers summarize
   tables, R helpers create scientific summaries and figures, and
   `pipeline_common.sh` provides shared shell functions.

The runner, stages, and helpers must come from the same saved pipeline revision.

## Before changing a file

- Start with one small change and keep notes about why you made it.
- Keep the stage order and the expected output file names unless you also
  understand every place that uses them.
- Preserve modified-base information. Do not remove the MM, ML, or MN BAM tags.
- 5mC and 5hmC are different measurements and should not be combined silently.
- CPU and memory limits do not stop custom code from accessing files available
  to your user account.
- A script can run without errors and still produce scientifically incorrect
  results. Review custom results carefully.

Missus Tom keeps the official pipeline unchanged. You can restore it from this
page if a custom version does not work.
