# Learn and Modify

## Goal

Provide an offline source viewer and safe, user-owned custom workflow revisions
for Bulk RNA-seq and ONT analysis.  Activated revisions must be selected by the
existing run system, never by editing installed resources.

## Scope and contracts

- Backend owns allowlisted source inventory, secure reads, immutable revision
  snapshots, active selection, source provenance, and source resolution.
- Desktop owns Learn and Modify, acknowledgement/editing flows, differences,
  pipeline state, and Settings safety controls.
- Bulk must run the selected workflow root so `main.nf`, config, and `bin/`
  scripts remain one revision.
- ONT custom execution must use an interpreter-backed launcher for the selected
  source tree; the packaged compiled sidecar remains only the official path.
- Existing containment, cancellation, logs, output locations, and official
  runs stay unchanged.

## Milestones

1. Investigate packaging/adapters and introduce tested source-management API.
2. Add read-only explorer/viewer and custom revision user interface.
3. Thread selected snapshot/provenance through run planning and both adapters.
4. Add restore/uninstall guidance and focused validation.

## Follow-up status

- Replaced the dependency-free viewer with CodeMirror 6 using Python plus
  legacy Groovy, R, and Shell language modes. `basicSetup` supplies line
  numbers, folding, search, matching brackets, history, indentation, and
  active-line support; the component recreates only on file/mode/edit-state
  changes.
- Added guided Debian uninstall detection in the Tauri host. It verifies both
  the release executable location and `dpkg-query` ownership of `missus-tom`,
  then exposes only the fixed command `sudo apt remove missus-tom`; no removal
  process or project-data deletion is initiated by the application.
- Added a short `START_HERE.md` to each packaged workflow and made the source
  service place it first. Older immutable custom revisions borrow the official
  guide for display until the user saves a new revision; the old revision is
  never modified in place.
- Active custom pipelines are labeled in both Learn and Modify and the New
  Project selector. New projects, edited projects, and opened projects receive
  a clear warning before their next run. The source explorer and CodeMirror
  editor now share one workspace panel with an internal left file column.
- Saving a custom file now preserves whether its official counterpart is
  executable. This prevents directly invoked workflow scripts from failing
  with `Permission denied` after an edit; regular source files remain private
  and non-executable.

## Safety decisions

- Permit a fixed, discovered workflow-file inventory only; reject traversal,
  symlinks, oversized/non-text content, and client absolute paths.
- Save revisions atomically below the application data root and retain the
  immutable selected revision for runs.
- Refuse activation/restoration while the relevant workflow is active.
- No self-uninstall or automatic deletion of projects, results, or inputs.

## Validation target

Focused backend source-management and adapter/run tests; desktop lint/tests/
typecheck/build; workflow parsing/configuration; Rust checks only if host code
changes. Packaged ONT custom-launch behavior requires packaging evidence or is
reported as manual acceptance work.
