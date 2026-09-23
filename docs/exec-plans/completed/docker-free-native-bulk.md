# Docker-free native Bulk RNA-seq

Managed native Bulk RNA-seq installation and execution, with the independent ONT
environment, scientific workflow, restart behavior, and local-only security
boundary preserved.

Owners: dependency service/API and Setup UI; Bulk adapter/workflow configuration;
RunManager lifecycle safeguards; tests, documentation, and release checks.

## Delivered

- Pinned Bulk Micromamba catalog: Nextflow 24.04.4, OpenJDK 17, FastQC 0.12.1,
  MultiQC 1.33, Cutadapt 5.2, Kallisto 0.52.0, R, DESeq2, tximport, and ggplot2.
  Docker is not part of normal dependency readiness or installation.
- `local` is the normal Nextflow profile (`docker.enabled = false`). The Docker
  profile remains for regression, including network-disabled containers,
  per-task CPU/memory-swap limits, and run labels.
- Container cleanup is required only for Docker-profile Nextflow runs. Admission
  locking, process groups, TERM/KILL escalation, recovery, named sessions, and
  resume still apply to every run.
- Setup classifies concurrent installation conflicts by HTTP 409 and the
  conflict message.
- Operator docs describe internet install of managed native tools, optional
  Docker for regression, and offline local-profile runs after install when
  references are already present.

## Validation

`./scripts/check.sh` passed on 2026-09-23 (log: `/tmp/missus-tom-check-stage5.log`):

- Ruff check and format, mypy (35 source files)
- pytest: 215 passed
- ESLint, frontend tests (16 passed), TypeScript, Vite build
- ONT synthetic contract tests: 12 passed, plus Bash syntax checks

Routine verification uses mocked installers, configuration inspection, and small
synthetic fixtures only.

## Not verified

Clean-machine internet installation and native-versus-Docker scientific
equivalence were not run. `scripts/agent/synthetic-workflow-smoke.sh` still
uses the Docker profile and cached images; it is a regression check, not proof
of the native install.

## Residual risks

- Probe timeouts were raised after review (Nextflow/Java 8s, R namespaces 30s).
- Managed `NXF_HOME` caches the engine under the Bulk dependency root; install
  verification still only runs `nextflow -version` with networking enabled.
- R/Bioconductor packages remain channel-solved rather than exact version pins
  (same pattern as ONT). CLI tools are exact pins.
- Docker regression images are no longer installed by Setup; operators must
  pull/build them separately for `-profile docker` or synthetic smoke.
- Clean-machine internet install and native-versus-Docker scientific equivalence
  remain unverified.
