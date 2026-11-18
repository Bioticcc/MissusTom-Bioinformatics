# FASTQ inputs and selectable chemistry

FASTQ processing is part of the first-version scope. The development entry point
is `run_fastq.py`; it runs STARsolo before the existing Seurat count analysis.
This source implementation is not yet installed or scientifically validated.

## Chemistry selection

You do not need to decide the chemistry when creating a draft. Keep `unknown`
until the sequencing provider or kit record confirms it. Execution requires a
confirmed supported selection and the corresponding local barcode whitelist.

```bash
python3 workflows/singlecell_rnaseq/run_fastq.py --list-chemistries
python3 workflows/singlecell_rnaseq/run_fastq.py --help
```

`chemistries.json` supplies labels, descriptions and availability for the desktop
selector under **New project → Pipeline → SingleCell RNA-seq**. Select chemistry
per library there, directly in the manifest, or with the runner's command-line choices:

```bash
python3 workflows/singlecell_rnaseq/run_fastq.py --manifest /path/fastq_manifest.json \
  --chemistry 10x_3prime_v3 --material cells --check-only
```

The CLI choices override those fields for **all** libraries and are recorded in
provenance. Use per-library fields when chemistries differ. The desktop screen
exports standalone configurations; app project saving and execution remain pending.

| Selection | Implementation |
| --- | --- |
| Not sure yet | Draft only; execution blocked |
| 10x 3′ v2 | 16-base cell barcode, 10-base UMI on R1; cDNA on R2 |
| 10x 3′ v3/v3.1 | 16-base cell barcode, 12-base UMI on R1; cDNA on R2 |
| 10x 3′ v4/GEM-X, 5′, Flex, other | Listed for clarity; execution unavailable pending separate implementation/validation |

Do not infer chemistry from filenames or choose a similar-sounding kit. Layout
alone does not establish the correct whitelist. Probe-based Flex, multiplexed
donors, feature barcodes, V(D)J and plate-based Smart-seq require other contracts.

## Confirmed inputs

Copy `example_fastq_manifest.json` outside the repo and replace the placeholders.
It intentionally blocks execution until chemistry, material, counting mode and
real paths are provided. All numeric settings are examples, not biological advice.

- **One sample = one capture/library.** Keep donors and conditions explicit.
  Multiplexed captures must be demultiplexed with a dedicated design; do not label
  all cells as one donor simply because they share FASTQs.
- **Lanes:** give paired gzip R1/R2 files in matching order. Multiple sequencing
  lanes from one library are combined before barcode correction/UMI counting.
  Reusing a FASTQ under another lane, mate or library is rejected.
- **Material:** select `cells` or `nuclei`. This label does not silently alter
  counting. Select `Gene` for exonic counts or `GeneFull` for exonic+intronic counts
  separately, according to the experiment. All libraries analyzed together must
  use the same counting mode.
- **Whitelist:** local uncompressed text, one chemistry-matched 16-base ACGT
  barcode per line. Obtain it from a documented provider distribution; the
  workflow neither downloads it nor certifies its chemistry from its contents.
- **Reference:** uncompressed local genome FASTA and matching GTF containing exon,
  gene_id and transcript_id annotations. Explicit species/build/annotation release
  and mitochondrial gene IDs remain required. STAR builds one shared index per run.
- **Index settings:** set `sjdb_overhang` to the intended maximum cDNA read length
  minus one. Choose `sa_index_n_bases` for the genome size: 14 is typical for a
  mammalian genome, whereas small test genomes require smaller values. STAR's
  documented guidance is `min(14, log2(genome_length)/2 - 1)`.
- **Cell calling:** set `expected_cells` per library. The implementation uses
  explicit `EmptyDrops_CR` settings rather than STAR's older default knee-only
  method. Cell calling precedes the independent per-cell QC cutoffs.

## Execution and retained outputs

```bash
python3 workflows/singlecell_rnaseq/run_fastq.py --manifest /path/fastq_manifest.json --check-only
python3 workflows/singlecell_rnaseq/run_fastq.py --manifest /path/fastq_manifest.json \
  --run-dir /path/new-fastq-run --cpus 4 --memory-gb 32
```

Preflight checks declarations, files, whitelist structure and first paired records.
It also streams FASTA/GTF to check contig names, exon coordinates/strand,
gene/transcript IDs, mitochondrial IDs and the small-genome index setting. Those
checks establish structural compatibility; they do not certify assembly identity.
Before mapping, the quantification task checks **every** FASTQ record for matching
read IDs, record counts, sequence/quality consistency and barcode-read length.
STAR then performs alignment, barcode correction, UMI deduplication and cell calling.
The paired-record scan is an additional sequential read of the FASTQs.

No Bulk-style trimming is applied to R1: it contains cell barcodes and UMIs.
STAR's explicit `CellRanger4` clipping handles the cDNA adapter/poly(A) step.
Multimapping counts are not redistributed: this increment uses STARsolo's integer
unique-gene UMI matrix. No expression downsampling or library-depth normalization
is applied before the Seurat stage.

- `input_manifest/`: original and prepared FASTQ settings/hashes, per-library task
  settings, generated count manifest.
- `reference/index_provenance.json`: exact index command/version. The large index
  remains in the retained Nextflow `work/` directory.
- `quantification/<sample>/Solo.out/`: raw and called-cell matrices, summary and
  STARsolo barcode/UMI statistics.
- `quantification/<sample>/matrix/`: deterministic gzip-packaged called-cell
  matrices. Packaging adds only the `Gene Expression` feature-type column when
  STAR emitted two columns; gene IDs, order and count values are preserved.
- `quantification/<sample>/`: STAR logs, exact command/version, paired-read report.
- `analysis/results/`: the existing Seurat outputs, with FASTQ manifest/hashes
  included under `tables/provenance/`.
- `reports/` and `analysis/reports/`: separate FASTQ and Seurat Nextflow reports.

The supported runner exits successfully only after both stages finish and the
final output checks pass. New run directories are required; resume and cross-run
reference-index reuse are future integration work. No BAM is emitted initially.
Native scheduling requests do not supply desktop process containment.

## Packages and validation

The candidate environment now includes **STAR 2.7.11b**, gzip, Python 3.11,
Nextflow/OpenJDK and the existing R packages. The runner and each STAR task enforce
the STAR version. All downloads/installations belong to setup, not execution.
The lock-generation script now also probes STAR and the native orchestration tools.

`SINGLECELL_TEST_NEXTFLOW=1` enables an actual two-library/two-lane FASTQ graph,
matrix handoff, and downstream orchestration test using replacement STAR/R tools.
That verifies wiring, not scientific equivalence. Real STAR/Seurat scientific
acceptance still needs the isolated environment and validated fixtures.

Primary references: [STARsolo instructions](https://github.com/alexdobin/STAR/blob/2.7.11b/docs/STARsolo.md)
and [STAR 2.7.11b parameters](https://github.com/alexdobin/STAR/blob/2.7.11b/source/parametersDefault).
The workflow does not claim equivalence to current Cell Ranger releases.
