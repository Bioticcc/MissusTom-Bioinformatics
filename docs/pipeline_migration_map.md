# Pipeline migration map

This document tracks two independent scientific baselines: the human short-read
bulk RNA-seq workflow and the mouse ONT modified-base workflow. They share the
application manifest/adapter boundary, but not input semantics, references, or
statistical assumptions.

## Human bulk RNA-seq

“Verified” describes baseline source behavior. The current boundary column
states whether behavior is implemented in the current human paired-end workflow
or remains planned.

| Baseline stage | Verified behavior | Proposed process / adapter boundary | Initial wrapping decision |
|---|---|---|---|
| Input discovery | Active shell scripts recursively accept `*.fastq.gz`, select `*_R1*`, and derive R2 by `_R1` → `_R2`. | `DISCOVER_FASTQ` remains an application service; a versioned channels builder consumes the confirmed manifest. | Do not wrap baseline discovery. Use the safer implemented scanner and user confirmation. |
| Raw read QC | FastQC in batches/retries, with failed batches retried one file at a time using one thread; output-pair checks, then MultiQC. | `FASTQC_RAW` and `MULTIQC_RAW`. | Implemented for included manifest samples and lanes with FastQC 0.12.1 and MultiQC 1.33. Native exit 134/139 retries once with each staged read isolated in a one-thread JVM; each isolated invocation can retry once for the same native exits. |
| Adapter trimming | Paired cutadapt, fixed adapters, `-m 20`, `-q 20`; existing outputs cause a skip. | `CUTADAPT_PAIRED` with explicit adapter/quality parameters and paired lanes per sample. | Implemented with Cutadapt 5.2 and validated manifest settings. |
| Clean read QC | FastQC/MultiQC on trimmed FASTQs, with the same one-file/one-thread native-crash fallback. | `FASTQC_CLEAN` and `MULTIQC_CLEAN`. | Implemented with declared HTML, ZIP, report, and data-directory outputs. |
| Kallisto index | Species-dependent transcript FASTA and reused index path. | A validated index path is supplied in the manifest. | A compatible human index is reused read-only. Index construction is not implemented. |
| Kallisto quant | Paired `--rf-stranded`; complete output means three nonempty files. | `KALLISTO_QUANT`, one task per confirmed sample. | Implemented with Kallisto 0.52.0; each task publishes `abundance.h5`, `abundance.tsv`, and `run_info.json`. A two-hour per-sample `run_with_timeout` foreground limit terminates and retries one stalled attempt before failing cleanly. |
| Transcript-to-gene map | GTF imported and converted through GenomicFeatures/txdbmaker/AnnotationDbi. | Target annotation plus reviewed BioMart mapping inside `FULL_HUMAN_ANALYSIS`. | Implemented for the fixed GENCODE v49 demo; general reference preparation remains future work. |
| Gene summarization | tximport reads per-sample kallisto outputs. | tximport section of `FULL_HUMAN_ANALYSIS`. | Implemented from `abundance.tsv`; inferential replicates are disabled because the quantification stage does not request bootstraps. |
| RNA class filter | lncRNA scripts grep `lncRNA`; mRNA scripts require `protein_coding`. | Class-specific sections of `FULL_HUMAN_ANALYSIS`. | Implemented with the observed rules; broader biotype policy still requires confirmation. |
| Count filter/model fit | DESeq2 count filter, `~group`, rlog, normal LFC shrinkage, fixed thresholds/resources. | DESeq2 section of `FULL_HUMAN_ANALYSIS`. | Implemented for manifest-defined two-group comparisons and thresholds. Batch/paired designs remain disabled. |
| Human comparisons | Metadata-driven H/OD1 and intervention follow-ups with minimum four per group. | Human design adapter produces a reviewed contrast/sample sheet. | Explicit manifest conditions and imported intervention metadata support baseline and intervention-filtered two-group contrasts; no filename-derived biology. |
| Mouse comparisons | Prefix/tissue parsing and four hardcoded contrasts across five tissues. | Mouse design adapter consumes explicit condition/tissue fields. | Replace biological filename inference before execution. |
| Plots | PCA, heatmap, volcano, MA, histograms, LFC density, distance, summary and UpSet plots. | Reporting section of `FULL_HUMAN_ANALYSIS`. | Implemented per manifest comparison; cross-comparison UpSet output remains future work. |
| Tables | Full/up/down/DE tables, normalized matrices, comparison summaries. | Reporting section of `FULL_HUMAN_ANALYSIS`. | Implemented with stable paths for mRNA, lncRNA, and combined summaries. |
| Logs/resume | Timestamped Bash/R logs; partial file-presence skips; no durable job ledger. | Nextflow trace/timeline/report plus application run-state JSON and captured stdout/stderr. | Implemented with a retained work directory and `-resume`; all 35 processes were verified as cached on a repeat run. SQLite job history remains future work. |

## Implemented end-to-end workflow

The workflow implements manifest-to-channel conversion, multi-lane raw
FastQC/MultiQC, paired Cutadapt, clean FastQC/MultiQC, kallisto quantification,
tximport, and separate mRNA/lncRNA DESeq2 analyses for each requested
comparison. The restricted demo remains an optional validated example.

## Mouse ONT modified-base analysis

The external `../ONTAnalysis` project remains read-only migration evidence. Its
machine-specific paths and installed binaries are not application defaults.

| Baseline stage | Preserved behavior | Application boundary |
|---|---|---|
| Pass modBAM input | Consume existing pass BAMs; never repeat basecalling; preserve `MM`, `ML`, and `MN`. | Explicit `ont_bam_files` in the confirmed manifest. Inputs must be regular, non-symlink files below the selected input directory. |
| Alignment | Align one BAM at a time, fully validate partial output and modification tags, atomically promote, and resume valid chunks. | `01_align_modbam`, using explicit reference FASTA, FAI, and minimap2 index resources. |
| Final alignment | Validate the complete expected chunk set, concatenate, coordinate-sort once, index, and reconcile record counts. | `02_finalize_alignment`, producing the canonical sorted modBAM and BAI. |
| ONT QC and coverage | Report alignment metrics, depth and breadth, chromosome/window coverage, and indexed coverage/gap tracks. | `03_ont_qc_coverage`; sequencing coverage remains distinct from modification-call coverage. |
| Methylation | Require joint 5mC/5hmC tags, combine CpG strands, retain 5mC and 5hmC separately, and calculate weighted summaries. | `04_methylation`, with explicit depth/filter parameters and auditable count denominators. |
| Exploration | Single-sample mouse QC, genome-wide/regional/feature plots, plot-data tables, report, dashboard, and session information. | `05_methylation_exploration` generates plots from analysis outputs; feature exploration uses an optional complete mouse annotation set. Existing figures are never inputs, and instrument-report HTML is optional provenance. Differential/DMR/enrichment outputs remain unavailable for one sample. |

The initial adapter is deliberately restricted to one `Mus musculus` sample on
`GRCm38p6`. It accepts no differential-expression comparisons. Expected source
BAM count, annotation assets, and runtime settings are manifest values rather
than global application assumptions. This separation also permits future human
and mouse distributions to package only their relevant adapters and workflows.
