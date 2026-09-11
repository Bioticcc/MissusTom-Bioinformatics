# Pipeline migration map

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
| Kallisto quant | Paired `--rf-stranded`; complete output means three nonempty files. | `KALLISTO_QUANT`, one task per confirmed sample. | Implemented with Kallisto 0.52.0; each task publishes `abundance.h5`, `abundance.tsv`, and `run_info.json`. A two-hour per-sample watchdog terminates and retries one stalled attempt before failing cleanly. |
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
