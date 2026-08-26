# Bulk RNA-seq full demo workflow

This Nextflow DSL2 workflow executes the controlled human demo only. It requires
eight prepared samples (four H and four OD1), the OD1-versus-H comparison, the
GENCODE v49 kallisto index, and the human BioMart annotation table.

Processes:

- `FASTQC_RAW`
- `MULTIQC_RAW`
- `CUTADAPT_PAIRED`
- `FASTQC_CLEAN`
- `MULTIQC_CLEAN`
- `KALLISTO_QUANT`
- `FULL_HUMAN_ANALYSIS`

The analysis process imports kallisto estimates, runs separate mRNA and lncRNA
DESeq2 analyses, and writes normalized matrices, differential-expression tables,
PCA, heatmaps, volcano/MA plots, distribution plots, sample distances, and
comparison summaries.

BioContainer inputs are pinned by SHA-256 digest in `conf/resources.config`.
The differential-expression image is built from the digest-pinned Bioconductor
base with `scripts/build-analysis-image.sh`. Containers run without network
access. Nextflow reports, trace data, and the work directory are retained for
auditing and `-resume`.

The backend is the supported execution boundary. It validates the complete demo
contract before invoking this workflow with a fixed argument array.
