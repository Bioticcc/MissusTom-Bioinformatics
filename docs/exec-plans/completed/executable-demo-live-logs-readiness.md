# Executable synthetic bulk demo, live logs, and readiness

Closing summary for the setup-wizard and synthetic-demo workstream (2026-09-23).

## Shipped

- **Dashboard — Run Bulk RNA-seq Demo**: prepares the local synthetic bulk fixture
  when needed (async job + consent), streams preparation output via live command
  logs, then opens the generated manifest and run plan.
- **Synthetic bulk demo bundle (v2)**: deterministic local generation (4 samples,
  24 transcripts, FASTQs, biomart/GTF) plus a real kallisto index built with
  managed Bulk tools; supports controlled local-profile workflow execution for
  functional validation only (not biological interpretation). ONT synthetic
  fixture remains UI-only (non-executable modBAM placeholder).
- **Live command logs**: incremental offset-based log APIs and shared
  `LiveCommandLog` UI for dependency install, demo prepare, and pipeline runs.
- **Readiness and storage**: system preflight, project/run disk admission, and
  dependency install gates use WSL-aware storage measurement; unconfirmed WSL
  virtual free space cannot green-light installs or strict launch. Docker and
  Apptainer are removed from default Dashboard readiness.

Docker Engine is not required for Setup, the Dashboard bulk demo path, or normal
local-profile Bulk runs; the Docker profile remains optional for regression.

## Validation (2026-09-23)

- Backend: `pytest` on `test_demos.py`, `test_resources.py`, `test_preflight.py`,
  `test_dependencies.py`, `test_runs.py`, `test_api.py` — pass after async prepare
  API test alignment.
- Desktop: `npm test`, `npm run typecheck` — pass (contract tests cover Dashboard
  demo flow, live command log polling, and Setup demo assets).

## Not verified on this machine

- Managed Bulk dependency tree under
  `~/.local/share/missus-tom/dependencies/bulk-rnaseq` was absent (no pinned
  kallisto/nextflow there); **native Nextflow E2E on the synthetic manifest was
  not run here**. Repeat on a host with Bulk deps installed and a temp
  `MISSUS_TOM_STATE_DIR`.
- Clean-machine GUI `.deb` install, clean-machine internet dependency install, and
  native-versus-Docker scientific equivalence remain manual follow-ups.
- WSL operators should confirm output paths on the intended filesystem; treat
  preflight storage warnings as authoritative when planning large runs.

## Supersedes

Historical planning context: [setup-wizard-demo-bundles.md](./setup-wizard-demo-bundles.md).
