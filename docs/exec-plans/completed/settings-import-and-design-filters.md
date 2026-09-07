# Settings import and design filters

Implemented September 2, 2026.

- Unsaved wizard state round-trips through versioned debug JSON exports.
- Imports restore editable state but require validation again.
- Rediscovery preserves confirmed design fields and removes comparisons whose
  groups no longer exist.
- Original human `SampleID`, `Patient`, `Condition`, `Batch`, and `Intervention`
  metadata is supported with reported legacy identifier normalization.
- All 232 samples in the inspected full human input set match the original
  patient table; duplicate metadata rows retain the baseline leading-`n`
  priority.
- Explicit intervention filters are carried from the manifest through Nextflow
  into each DESeq2 comparison.

Validation completed with 63 backend tests, Ruff, mypy, ESLint, TypeScript,
Vite build, Rust format/check, R parse, Nextflow config, and an
intervention-filtered Nextflow preview.
