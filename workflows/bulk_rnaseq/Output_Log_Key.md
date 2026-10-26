# Bulk RNA-seq output log key

This is a read-only reference for the live run log shown in Missus Tom. A line
usually tells you either which workflow step is running, what an external tool
reported, or why a run stopped. The text is diagnostic information; it does
not by itself establish that a scientific result is valid.

## Missus Tom records

| Header or pattern | Meaning | Information used |
| --- | --- | --- |
| `[Missus Tom lifecycle]` | Application-owned queue, validation, heartbeat, cleanup, cancellation, and final-status record. | Run state and UTC time. These records are protected. |
| `Heartbeat at ... workflow is still running` | The backend has not observed a terminal process state. It is a liveness marker, not a progress percentage. | Current elapsed run time. |
| `Completed at ...`, `Failed at ...`, or `Cancelled at ...` | Terminal application record after the runner has ended and cleanup state has been persisted. | Final run status and UTC time. |
| `[Task out: PROCESS]` | Bounded preview of stdout from one submitted Nextflow task. | The Nextflow process name and that task's stdout. |
| `[Task err: PROCESS]` | Bounded preview of stderr from one submitted Nextflow task. Stderr is diagnostic; some tools write normal progress there. | The Nextflow process name and that task's stderr. |

## Nextflow records

| Header or pattern | Meaning | Information used |
| --- | --- | --- |
| `N E X T F L O W` | Nextflow engine startup banner. | Nextflow version and launch context. |
| `executor >` | Nextflow executor summary, commonly `local` for local execution. | Selected executor and task counts. |
| `[-        ] PROCESS` | A process has not yet started, or no task for it has been submitted. | Process name only. |
| `[ab/cdef12] PROCESS (sample)` | A task was submitted or completed. `ab/cdef12` is a Nextflow work-directory hash, not an error code or biological value. Text in parentheses is usually the process tag, such as a sample ID. | Process name, work hash, and optional task tag. |
| `Submitted process > PROCESS` | Nextflow has handed a process to its executor. | Process name and task hash. |
| `ERROR ~` | Nextflow stopped because a process or workflow-level check failed. Read the surrounding task output and the final lines for the underlying command/tool error. | Nextflow error message and failed process context. |

## Tool-specific records

| Header or pattern | Meaning | Information used |
| --- | --- | --- |
| `[quant]` | Kallisto quantification progress or summary. It can report index use, read processing, fragment-length estimation, and output completion. | Kallisto's input reads, index, and quantification settings. |
| `[em]` | Kallisto expectation-maximization (EM) algorithm progress while estimating transcript abundances. Iteration/convergence text is normal unless followed by an explicit error. | Kallisto equivalence classes and abundance estimates. |
| `cutadapt:` or `This is cutadapt` | Adapter-trimming program startup/progress/summary. | Read files, adapter sequences, quality and length settings. |
| `FastQC` | FastQC report generation. Detailed quality findings belong in the generated HTML report, not the console line alone. | FASTQ input and FastQC checks. |
| `MultiQC` | MultiQC report aggregation. | Existing tool report files. |
| `Loading`, `Importing`, `Running DESeq2`, `Computing rlog/PCA`, `Writing figures and tables`, `Analysis complete` | Missus Tom's R analysis progress messages. | The saved sample sheet, comparisons, Kallisto abundance tables, and configured analysis parameters. |

## What to do with an unfamiliar line

1. Identify the nearest process name or prefix above it.
2. Read several lines before and after it; the first explicit `ERROR`, exit
   status, or missing-file message is usually more useful than later fallout.
3. For a failed Nextflow task, retain the work hash and process name when
   reporting the issue. Do not treat the hash as a sample identifier.
