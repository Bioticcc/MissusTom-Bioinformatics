# Bulk RNA-seq workflow

This Nextflow DSL2 workflow executes human paired-end bulk RNA-seq projects from
a saved manifest. It accepts any number of included samples, paired FASTQ lanes,
and manifest-defined two-group comparisons with optional explicit intervention
filters. A compatible kallisto index and human BioMart annotation table must be
supplied.

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
auditing and `-resume`. Local tasks have no fixed wall-time limit because input
size and analysis duration vary; operators can cancel a stuck run explicitly.
A task terminated by a native segmentation fault (exit 139) is retried once;
Kallisto also retries a native abort (exit 134) once. Other failures terminate
immediately so validation, resource, and operator errors are not hidden by
automatic restarts.

## Local resource containment

`--max_cpus` and `--max_memory_gb` are total local-executor admission budgets,
not per-task parallelism settings. Each process requests no more than those
budgets, and the local executor reserves requested CPU and memory across active
tasks. `--max_parallel_tasks` is the local executor queue-size cap, so it limits
the total number of task processes submitted at once rather than only one
process type. The three resource parameters must be positive values;
`max_cpus` and `max_parallel_tasks` must be whole numbers and
`max_memory_gb` must be finite.

For the Docker profile, each task also receives a hard `--cpus` limit equal to
its resolved `task.cpus`. Nextflow supplies each task's Docker memory limit from
its process `memory` directive, and the workflow sets Docker `--memory-swap` to
that same value so the task cannot grow into host swap. The R analysis command
caps common BLAS/OpenMP thread environment variables at one; this avoids nested
linear-algebra thread pools while leaving the analysis calculations unchanged.

The backend passes a UUID as `--run_id` for application-launched workflows. It
is validated before any task starts and becomes the Docker label
`missus_tom.run_id=<UUID>`, allowing the runner to identify only containers
belonging to that job. The parameter is optional for direct command-line use.

Single-lane paired inputs are passed directly to Cutadapt from their staged
paths. For multi-lane samples, each read direction is concatenated in manifest
order before Cutadapt so all lane content is retained. The concatenated files
remain in the retained work directory to preserve the existing `-resume` and
audit behavior.

Runs start with quantification by default, including FASTQ QC, trimming,
kallisto, and the full downstream analysis. Analysis-only runs skip FASTQ
processing and consume each sample's manifest-assigned Kallisto `abundance.tsv`,
falling back to `results/counts/kallisto/<sample_id>/abundance.tsv` for projects
previously quantified by Missus Tom.

The backend is the supported execution boundary. It validates the manifest,
input containment, references, parameters, comparison group sizes, and runtime
before invoking this workflow with a fixed argument array.
