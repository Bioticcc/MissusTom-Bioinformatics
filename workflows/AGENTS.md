# Workflow-specific guidance

These instructions apply under `workflows/` in addition to the root guide.

## Boundaries and sources

- `bulk_rnaseq/main.nf` is the executable DSL2 graph.
- `bulk_rnaseq/nextflow.config` owns profiles, reports, trace, retry policy, and
  minimum Nextflow version.
- `bulk_rnaseq/conf/resources.config` owns process resources and pinned runtime
  images. `bulk_rnaseq/docker/Dockerfile.analysis` owns the local R image.
- `bulk_rnaseq/bin/full_human_analysis.R` implements the fixed mRNA/lncRNA
  statistical analysis for the restricted eight-sample demo.
- The verified scientific baseline is external and read-only. Use
  `docs/baseline_pipeline_inventory.md` and `docs/pipeline_migration_map.md` as
  evidence; do not copy new behavior from the baseline without reviewing it.

## Scientific and execution rules

- Do not infer biological groups, pairing, tissues, contrasts, or covariates
  from filenames. Consume confirmed manifest fields.
- Preserve the supported demo contract documented in the root `README.md` and
  `docs/pipeline_migration_map.md`. Generalization requires explicit product and
  scientific decisions.
- Keep container inputs digest-pinned. Record deliberate tool, R, Bioconductor,
  or package changes in the appropriate workflow documentation.
- Containers remain network-disabled during workflow execution.
- Preserve declared outputs, audit reports, trace data, retained work directory,
  and `-resume` behavior unless the task explicitly changes those contracts.
- Do not read restricted FASTQ/reference/result contents to validate a source
  change when syntax, config, fixtures, or metadata are sufficient.
- Never edit runtime `work/`, `results/`, reports, logs, `.nextflow/`, or other
  generated artifacts as source.

## Validation

- For config-only changes, render Nextflow configuration to a file under `/tmp`
  and inspect errors rather than printing the full resolved config.
- Parse the R file before any image build or real analysis run.
- Build the analysis image only for Dockerfile or R dependency changes.
- Run the real demo only when execution semantics or scientific outputs changed
  and the restricted local prerequisites are available.
- Exact commands and escalation order are in `docs/agent/WORKFLOWS.md`.
