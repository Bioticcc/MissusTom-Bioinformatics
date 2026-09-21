# ONT analysis integration

## Goal

Add a selectable mouse ONT modified-base analysis pipeline while preserving the
existing human bulk RNA-seq workflow and keeping future species-specific
packaging boundaries explicit.

## Contracts

- Pipeline identifier: `ont-analysis`, initial version `0.1.0`.
- Input: user-selected pass modBAM files with explicit sample ownership; never
  infer biology from filenames.
- Initial scientific scope: one `Mus musculus` / `GRCm38p6` sample, descriptive
  5mC/5hmC analysis, no comparisons or differential statistics.
- Stages: alignment, alignment finalization, ONT QC/coverage, methylation, and
  methylation exploration.
- Existing `../ONTAnalysis` is read-only migration evidence. No data, generated
  results, local tool installs, or machine-specific paths enter this repository.
- Execution remains local and controlled through fixed argument arrays with no
  data upload.

## Workstreams

- [x] Manifest/schema, adapter registry, pipeline-specific validation, API and
  runner generalization.
- [x] Pipeline-aware desktop wizard and neutral run/dashboard presentation.
- [x] Manifest-driven ONT workflow assets and runner.
- [x] Documentation and focused/broad validation.

## Acceptance

- Both pipelines are listed and selected by manifest identifier.
- Existing bulk manifests and tests remain valid.
- The UI can build/save/plan an ONT manifest without fake DE comparisons.
- ONT inputs/references are path-validated and execution uses no arbitrary shell
  command from the UI.
- Workflow sources contain no source-project absolute paths and pass available
  syntax/static tests.
- Full restricted ONT data execution is not required for source integration.

## Completion evidence

The selectable pipeline, registry, native-run lifecycle, manifest contracts,
reference/BAM validation, resource admission, and artifact discovery are
implemented. The UI exposes coverage/methylation parameters and hides the
unsupported forced-rebuild mode for ONT. Full migrated Stage 03/04 helpers and
Stage 05 R are retained, with stable configuration-based stage invalidation,
partial-output gates, and reusable interrupted CpG pileup work.

Validation: `scripts/check.sh` passed (126 backend tests; frontend lint, tests,
typecheck, build; ten ONT synthetic tests; shell syntax checks). The migrated R
source also parsed successfully. Synthetic fixtures check separate 5mC/5hmC
coverage-weighted denominators and missing paired-call rejection.

Coverage and methylation windows must share coordinates for exploration; the
wizard uses one setting for both, and preflight/native validation enforce this.
Report headings avoid claiming a fixed 100 kb size when windows are modified.

No restricted ONT data run has been performed. Native tools, R dependencies,
the mouse reference bundle, and scientific parity still require an operator
acceptance run. Species-specific installers are future work; workflow/runtime
boundaries are separate, but this change does not split the app distributions.
