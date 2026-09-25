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

`local` is the normal Nextflow profile. It sets `docker.enabled = false` and
runs these processes with managed native tools on the local executor. `docker`
is retained for regression: it enables Docker, keeps containers off the
network, applies per-task CPU and memory-swap limits, and labels containers
with the run id. Digest-pinned BioContainer inputs in `conf/resources.config`,
and the differential-expression image built by `scripts/build-analysis-image.sh`,
apply to that Docker profile. Routine tests have not compared native-tool and
Docker-profile scientific outputs.

Nextflow reports, trace data, and the work directory are retained for
auditing and `-resume`. Most local tasks have no fixed wall-time limit because
input size and analysis duration vary. Each per-sample Kallisto quantification
has a two-hour wall limit via `bin/run_with_timeout`. The helper runs Kallisto in
the foreground under portable `timeout -s TERM -k 60 7200`, maps timeout exits to
240, and leaves ordinary command statuses unchanged. Kallisto retries that timeout once,
then fails the run cleanly if the second attempt also reaches two hours. A task
terminated by a native segmentation fault (exit 139) is retried once; FastQC and
Kallisto also retry a native abort (exit 134) once. FastQC normally
analyzes the staged reads for one sample together with up to two task threads.
On its native-crash retry, it invokes FastQC separately for every staged read
with one thread, isolating R1, R2, and any lanes in separate JVM processes while
preserving every declared report. Each isolated read gets one additional attempt
if its first one-thread invocation exits 134 or 139. The retry count is bounded;
an isolated read that crashes twice, or any other failure, terminates the task so
validation, resource, and operator errors are not hidden by automatic restarts.

This fallback preserves a reliability lesson from the original BulkRnaSeq
scripts. Those scripts reduced normal FastQC execution from 16 to eight threads
and batches of 32 files, but historical runs still encountered intermittent JVM
crashes. Retrying each file separately with one thread allowed all 464 human and
142 mouse FASTQ report pairs to validate. The number eight was the normal batch
thread setting; the proven recovery mechanism was one file in a one-thread JVM.
This changes execution isolation only, not FastQC inputs, version, reports, or
interpretation.

Kallisto uses `run_with_timeout` rather than Nextflow's `time` directive or a
background sleep monitor. Supported local-executor versions can report a timeout
without a usable exit status, preventing the configured retry from running.
Exit 240 is reserved for the normalized two-hour limit. No userspace timeout
wrapper can reap a process blocked indefinitely in uninterruptible kernel I/O.
On the Docker profile, owned-container cleanup remains the final safety mechanism
for that operating-system failure mode.

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
is validated before any task starts. On the Docker profile it becomes the
container label `missus_tom.run_id=<UUID>`, so cleanup can identify only
containers belonging to that job. The parameter is optional for direct
command-line use.

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
