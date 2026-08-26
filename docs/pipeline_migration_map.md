# Pipeline migration map

“Verified” describes baseline source behavior. The current boundary column
states whether behavior is implemented in the controlled 0.3.0 demo or remains
planned.

| Baseline stage | Verified behavior | Proposed process / adapter boundary | Initial wrapping decision |
|---|---|---|---|
| Input discovery | Active shell scripts recursively accept `*.fastq.gz`, select `*_R1*`, and derive R2 by `_R1` → `_R2`. | `DISCOVER_FASTQ` remains an application service; a versioned channels builder consumes the confirmed manifest. | Do not wrap baseline discovery. Use the safer implemented scanner and user confirmation. |
| Raw read QC | FastQC in batches/retries, output-pair checks, then MultiQC. | `FASTQC_RAW` and `MULTIQC_RAW`. | Implemented for the eight-sample demo with FastQC 0.12.1 and MultiQC 1.33. |
| Adapter trimming | Paired cutadapt, fixed adapters, `-m 20`, `-q 20`; existing outputs cause a skip. | `CUTADAPT_PAIRED` with explicit adapter/quality parameters and one pair per demo sample. | Implemented with Cutadapt 5.2 and the verified baseline values; the backend gate checks the manifest values. |
| Clean read QC | FastQC/MultiQC on trimmed FASTQs. | `FASTQC_CLEAN` and `MULTIQC_CLEAN`. | Implemented for the demo with declared HTML, ZIP, report, and data-directory outputs. |
| Kallisto index | Species-dependent transcript FASTA and reused index path. | A validated index path is supplied in the demo manifest. | The demo reuses the existing GENCODE v49 human index read-only; its SHA-256 is recorded in restricted provenance. Index construction is not implemented. |
| Kallisto quant | Paired `--rf-stranded`; complete output means three nonempty files. | `KALLISTO_QUANT`, one task per confirmed sample. | Implemented with Kallisto 0.51.1; each task publishes `abundance.h5`, `abundance.tsv`, and `run_info.json`. |
| Transcript-to-gene map | GTF imported and converted through GenomicFeatures/txdbmaker/AnnotationDbi. | Target annotation plus reviewed BioMart mapping inside `FULL_HUMAN_ANALYSIS`. | Implemented for the fixed GENCODE v49 demo; general reference preparation remains future work. |
| Gene summarization | tximport reads per-sample kallisto outputs. | tximport section of `FULL_HUMAN_ANALYSIS`. | Implemented from `abundance.tsv`; inferential replicates are disabled because the quantification stage does not request bootstraps. |
| RNA class filter | lncRNA scripts grep `lncRNA`; mRNA scripts require `protein_coding`. | Class-specific sections of `FULL_HUMAN_ANALYSIS`. | Implemented with the observed rules; broader biotype policy still requires confirmation. |
| Count filter/model fit | DESeq2 count filter, `~group`, rlog, normal LFC shrinkage, fixed thresholds/resources. | DESeq2 section of `FULL_HUMAN_ANALYSIS`. | Implemented for OD1 versus H with four samples per group, `padj < 0.05`, and `|log2FC| > 0.30`. Batch/paired designs remain disabled. |
| Human comparisons | Metadata-driven H/OD1 and intervention follow-ups with minimum four per group. | Human design adapter produces a reviewed contrast/sample sheet. | Do not infer from filenames; manifest metadata must override source conventions. |
| Mouse comparisons | Prefix/tissue parsing and four hardcoded contrasts across five tissues. | Mouse design adapter consumes explicit condition/tissue fields. | Replace biological filename inference before execution. |
| Plots | PCA, heatmap, volcano, MA, histograms, LFC density, distance, summary and UpSet plots. | Reporting section of `FULL_HUMAN_ANALYSIS`. | Implemented for all applicable single-comparison plots. Multi-comparison UpSet output is not applicable to the one-contrast demo. |
| Tables | Full/up/down/DE tables, normalized matrices, comparison summaries. | Reporting section of `FULL_HUMAN_ANALYSIS`. | Implemented with stable paths for mRNA, lncRNA, and combined summaries. |
| Logs/resume | Timestamped Bash/R logs; partial file-presence skips; no durable job ledger. | Nextflow trace/timeline/report plus application run-state JSON and captured stdout/stderr. | Implemented with a retained work directory and `-resume`; all 35 processes were verified as cached on a repeat run. SQLite job history remains future work. |

## Implemented end-to-end demo slice

The internal demo uses four pseudonymous H and four pseudonymous OD1 libraries,
each limited to 1,000,000 paired reads. It implements manifest-to-channel
conversion, raw FastQC/MultiQC, paired Cutadapt, clean FastQC/MultiQC, and
kallisto quantification, tximport, and separate mRNA/lncRNA DESeq2 analyses.
Containers use pinned inputs, output contracts are checked by Nextflow, and
source mapping/checksums remain in restricted local provenance.
