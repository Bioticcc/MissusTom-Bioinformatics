# Multi-pipeline setup and synthetic demo bundles

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
- Clean-VM installation and executable synthetic-demo validation remain
  deferred. The prepared fixtures are deliberately non-executable and are not
  evidence of scientific or end-to-end runtime readiness.

## Completion boundary

The safe setup scope is complete when the dedicated multi-selection UI and
synchronous synthetic-demo contract are implemented with isolated frontend and
backend tests. The demo bundles remain deliberately non-executable: both
pipelines must still be prepared and launched on a clean supported machine
before any end-to-end readiness can be claimed. During the active ONT run,
completion remains limited to safe setup UI, packaging infrastructure, and
isolated contract tests.
