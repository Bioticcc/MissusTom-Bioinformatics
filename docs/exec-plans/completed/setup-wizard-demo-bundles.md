# Multi-pipeline setup and synthetic demo bundles

> **Completed (2026-09-23).** Executable synthetic bulk demo preparation, Dashboard
> **Run Bulk RNA-seq Demo**, live preparation logs, and readiness/storage checks
> shipped. See [executable-demo-live-logs-readiness.md](./executable-demo-live-logs-readiness.md)
> for the closing summary. Planning notes below are historical.

## Goal

Provide a dedicated setup experience where an operator can select Bulk RNA-seq,
ONT analysis, or both; install each selected pipeline's managed dependencies;
and prepare extremely small, regeneratable synthetic demo assets suitable for
installation and smoke testing on each supported machine. Generated manifests
embed absolute local paths, and their hashes provide corruption/self-consistency
checking rather than trusted tamper-proof integrity.

## Safety boundary for the active ONT run

- Do not stop or restart the backend.
- Do not modify `workflows/ont_analysis/` while the current run is active.
- Do not write to the active project, manifest, inputs, logs, or results under
  `/mnt/20TB_A/Adam/MissusTomDemo/outputs/ONT_test`.
- Keep validation isolated to temporary directories and focused frontend or
  backend tests. Do not install packages or launch demos during development.

## Decisions

- Project manifests remain single-pipeline. Multi-selection belongs to the app
  setup experience, not the scientific project contract.
- Demo assets are deterministic and synthetic. Do not package the restricted
  human demo, mouse data, GRCm38 references, or provenance-bearing outputs.
- Generate tiny demo assets locally from repository code instead of downloading
  biological data. Internet downloads remain limited to separately consented
  third-party dependency installation.
- Treat demo preparation and full workflow execution as different states. A
  prepared fixture must not be described as a scientifically representative run.
- Dependency installations run sequentially because the installer and pipeline
  runner share exclusive admission controls.

## Workstreams

1. Add a dedicated multi-pipeline Setup screen and navigation entry.
2. Add a fixed-catalogue demo status/preparation API with persistent metadata,
   deterministic synthetic fixture generation, and focused tests.
3. Connect the UI to preparation status and sequential actions.
4. After the active ONT run completes, add and validate any ONT workflow/demo
   mode required for end-to-end execution; do not perform this step beforehand.
5. Verify clean-install documentation and run the smallest representative smoke
   checks before claiming cross-device demo readiness.
6. Keep the managed ONT installer restricted to the reviewed official Dorado
   archive, and re-verify the pin before any future archive upgrade.

## Progress

- Setup selection, dependency cards, and synthetic-demo preparation contracts
  are implemented with isolated application tests.
- Linux release packaging now has a tag-only CI path that builds Tauri sidecars,
  uses temporary state for a loopback-only packaged-backend smoke check, and
  packages release-only workflow resources. It intentionally does not package
  demo data, ONT data, references, runtime outputs, or dependency environments.
- The managed installer pins the reviewed Dorado 2.1.2 official archive and
  fails closed when its SHA-256 does not match. It has not been installed into
  or exercised against the active ONT environment.
- Executable synthetic bulk demo, async preparation jobs, live logs, and Dashboard
  entry shipped with contract tests; clean-VM GUI install and full native E2E on
  every target host remain operator verification (see closing summary doc).
- Bulk fixture version 3 invalidates older/non-executable bundles and saves the
  exact manifest used by the adapter at
  `project-output/input_manifest/project_manifest.json` before it is offered for execution.

## Completion boundary

Met for in-repo scope: multi-pipeline Setup UI, async synthetic-demo API, bulk
functional execution support when managed tools are present, live command logs,
and isolated frontend/backend tests. ONT synthetic bundle remains non-executable
by design. Cross-machine readiness still requires managed Bulk install plus a
local-profile smoke run on each environment.
