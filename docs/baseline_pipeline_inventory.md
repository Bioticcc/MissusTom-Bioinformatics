# Baseline pipeline inventory

## Scope and evidence

This inventory was produced from text and metadata under the read-only baseline
`/home/kyle/Desktop/Adam/BulkRnaSeq/bulkRNAseq`. No pipeline command was run, no
biological data was opened, and no baseline file was changed. Observations came
from `setup.md`, `analysis_notes.md`, `AI_HANDOFF_SUMMARY.md`, `scripts/README.md`,
the active shell/R scripts, small historical shell scripts, reference filenames,
the human metadata header, and output names/directories. Generated result
contents, FASTQs, BAMs, archives, images, RDS/RData, HDF5, GTF/FASTA bodies, and
large logs were not read.

Statements marked **Verified** are present in source. **Inference** identifies a
proposed interpretation that still needs confirmation.

## Apparent entry points and active order

**Verified:** the documented production entry points are:

1. `scripts/QC_n_Quantification_H.sh [sample_dir] [workdir]`
2. `scripts/QC_n_Quantification_M.sh [sample_dir] [workdir]`
3. `Rscript scripts/Human_lncRNA_analysis_pipeline.R`
4. `Rscript scripts/Human_mRNA_analysis_pipeline.R`
5. `Rscript scripts/Mouse_lncRNA_analysis_pipeline.R`
6. `Rscript scripts/Mouse_mRNA_analysis_pipeline.R`

The shell scripts implement four numbered stages:

1. FastQC over raw FASTQ files, followed by MultiQC.
2. Paired adapter and quality trimming with cutadapt (`-m 20`, `-q 20`, fixed
   TruSeq adapter sequences).
3. FastQC over trimmed files, followed by MultiQC.
4. Kallisto transcriptome index construction/reuse and paired quantification
   with `--rf-stranded`.

The R scripts then locate per-sample `abundance.h5`, construct a transcript-to-
gene map from GTF, import with tximport, select lncRNA or `protein_coding` genes,
filter counts, fit DESeq2 models, generate rlog-based diagnostics, and write DE
tables, normalized matrices, plots, and comparison summaries.

`scripts/QC_Original.sh`, `scripts/analysis_Original.R`, and
`scripts/ScriptsFromReuben/` are documented or structured as historical/reference
logic rather than the current production flow.

## Languages and dependencies observed

**Verified active languages:** Bash and R. There is an RStudio project. No
Python, Nextflow, Dockerfile, Compose file, Conda YAML, `renv.lock`, requirements
file, or package lock was found in the baseline.

**Verified active command-line tools:** `fastqc`, `multiqc`, `cutadapt`,
`kallisto`, plus standard `find` and `sort`. Java is used by FastQC, with a
preferred hardcoded Java 17 location and a PATH fallback.

**Verified historical/reference tools:** STAR, HISAT2/hisat2-build, samtools,
featureCounts (Subread), Qualimap, fastp, and Kraken2 (some calls are commented).
These are not claimed as part of the current kallisto production path.

**Verified R/Bioconductor packages loaded or namespace-qualified by the four
current analysis scripts:** AnnotationDbi, BiocParallel, DESeq2, GenomicFeatures,
SummarizedExperiment, UpSetR, biomaRt, dplyr, ggplot2, ggrepel, htmlwidgets,
limma, org.Mm.eg.db, plotly, reticulate, rstudioapi, rtracklayer, scales, stringr,
tidyr, tidyverse, tools, txdbmaker, and tximport. Some calls are optional or
commented; `setup.md` installs a subset and is not a complete reproducible lock.

## Inputs and naming assumptions

**Verified shell inputs:** recursive files ending exactly in `fastq.gz`. Read 1
must match `*_R1*fastq.gz`; read 2 is obtained by replacing the first `_R1` with
`_R2`. Both active scripts therefore assume paired-end data. Single-end support
exists only in historical alignment scripts.

The sample output name is the trimmed R1 basename with `_R.*` removed. Multiple
lanes are not explicitly modeled. **Inference:** lane files sharing that prefix
may target the same kallisto output directory sequentially, so lane merging and
overwrite behavior must be tested rather than wrapped blindly.

**Verified R inputs:** one immediate child directory per sample under
`kallisto_samples`, each containing `abundance.h5`. Human scripts normalize
several old/new sample-ID conventions and prefer `P50Large_` duplicates. The
human CSV header contains `Patient`, `SampleID`, `Condition`, `Intervention`,
`Intervention_name`, `Group2Factors`, `Batch`, and `BMI`; the code requires
`SampleID`, `Condition`, and `Intervention` and reads optional `Patient` and
`Batch`.

## Reference assumptions

- Human quantification: `inputs/references/gencode.v49.transcripts.fa`.
- Human analysis: `gencode.v49.annotation.gtf`,
  `Human_GRCh38_Ensembl_Biomart.txt`, and
  `Patients_table_LargeRNA_2026Feb23(All_NEWsamples).csv`.
- Mouse quantification: the first available transcript FASTA from four hardcoded
  GENCODE vM38/vM36 candidate paths.
- Mouse analysis: `mouse_gencode_vM36/gencode.vM38.annotation.gtf` and
  `Mouse_GRCm39_Ensembl_Biomart.txt`.

**Uncertainty:** the mouse directory name says vM36 while its required GTF
basename says vM38; the intended release pairing and genome/transcriptome
compatibility require scientific confirmation.

## Hardcoded paths, biology, and analysis choices

- Default input/output roots point to `/mnt/20TB_A/Adam/bulkRNASeq/...`.
- The shell scripts prefer `/usr/lib/jvm/java-17-openjdk-amd64`.
- Threads default to 16 overall, 8 for FastQC, 12 for kallisto, and 16 in R.
- Kallisto is fixed to reverse/RF stranded paired-end mode.
- DE uses `q_value = 0.05`, absolute LFC `0.3`, count filtering at 10 reads in at
  least the smallest group, rlog transforms, and DESeq2 normal LFC shrinkage.
- Mouse treatment is inferred from sample-ID prefixes `HFD`, `ICD`, `RHFD`, and
  `RICD`; tissue is inferred from `sperm`, `islet`/`-is`, `muscle`, `liver`, and
  `brain` tokens.
- For every mouse tissue, source code constructs `HFD vs ICD`, `RHFD vs RICD`,
  `RHFD vs HFD`, and `RICD vs ICD` (numerator first). The handoff document also
  contains `HFDvsRHCD`, which does not match the active code and appears to be a
  typo or stale description.
- Human source builds baseline `OD1` (case) vs `H` (reference), plus each of
  `OW12`, `OW24`, and `OW48` (case) vs `OD1` (reference) within intervention
  codes `D`, `DE`, `E`, and `NI`, only with at least four samples per group.
- Human `Patient` and `Batch` are read, but the active comparison design is
  `~group`; the optional batch-removal branch is not passed by these comparison
  calls. No paired-patient term is present in the verified active design.
- Plot names, colors, camera positions, tissues, thresholds, and output trees are
  embedded in R source.

These are all current code behavior, not safe biological defaults for a generic
GUI.

Historical FastQC reliability evidence clarifies the eight-thread default. Older
human runs passed all FASTQs to a single 16-thread FastQC JVM and repeatedly
ended with native `SIGSEGV`/exit 134 failures. Later scripts used eight threads
and batches of 32 files, but native crashes still occurred. Their recovery path
retried each affected FASTQ separately with `fastqc -t 1`, allowing up to two
one-thread attempts per file; dated human and mouse logs show that fallback
completing and validating all expected reports. Thus
eight was the reduced normal batch setting, while one file in a one-thread JVM
was the effective crash fallback. This is execution-reliability evidence and
does not change QC interpretation.

## Outputs observed

QC/quantification writes raw and clean FastQC/MultiQC reports, trimmed FASTQs,
kallisto indexes, and per-sample `abundance.h5`, `abundance.tsv`, and
`run_info.json`.

Analysis code and output names show transcript/gene count tables, full/up/down/DE
TSVs, rlog and library-size normalized CSVs, comparison status/count summaries,
2D and 3D PCA, scree, heatmap, volcano, MA, p-value and adjusted-p-value
histograms, LFC density, sample-distance heatmaps, UpSet plots, and PDF/PNG/HTML
artifacts. Human and mouse output roots distinguish `lncOutputs` and `mOutputs`.

## Logging, errors, and restart behavior

The current QC scripts use `set -Eeuo pipefail`, structured timestamped log
helpers, quoted argument-array command execution, ERR/EXIT traps, required-tool
checks, retry loops, and output validation. They skip complete FastQC report
pairs and cutadapt outputs and can reuse kallisto indexes and complete sample
outputs. MultiQC reruns. Kallisto retries remove three files in the target sample
directory before retrying.

The R scripts sink output/messages to timestamped logs and install a traceback
handler. They restart from the beginning; output functions generally overwrite
files or fall back to timestamped names if removal fails. There is no durable
stage ledger, input checksum, version capture, or transactional run state.

**Conclusion:** QC stages have useful local resume guards but are not a complete
resumability contract. R stages are not safely stage-resumable. Existing scripts
can initially be invoked behind tightly validated adapters in controlled tests,
but paths, lane handling, references, resources, experimental designs, and
outputs must be parameterized before general use.
