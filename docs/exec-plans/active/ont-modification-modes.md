# ONT modification modes and legacy BAM compatibility

User approved 5mC-only support alongside joint 5mC/5hmC processing after the first
human run failed its uppercase-MM/ML/MN probe. The index and alignment completed.
Bounded samples from the source and aligned BAM both had Mm/Ml and no MN; sampled
codes showed C+m only. These observations do not establish the calling model's
age or prove that all records in every downloaded BAM lack 5hmC.

Implemented contract:

- Explicit `parameters.modification_mode`: `5mc_only` or backward-compatible
  `5mc_5hmc`. UI, editor/import/export, model/schema, preflight and runner agree.
- Primary-read probe accepts modern or legacy tags. Existing MN is checked;
  missing MN is allowed. It runs before reference generation/alignment.
- Generated alignments stream through tag-name normalization. No probabilities,
  codes, implicit/explicit modes or records change. MN is not fabricated. Original
  inputs are read-only; Modkit defaults to primary alignments.
- Stage 04 validates the selected modification set, uses mode-specific filenames,
  and preserves weighted denominators. Other-modification counts cannot be
  silently absorbed into 5mC-only results. Unmeasured 5hmC columns are NA, with
  an explicit not_measured status. A measured joint-mode zero remains zero.
- Both core and annotation-aware R reports support the modes. 5hmC-specific
  figures/rankings are omitted in 5mC-only mode. Report fixes also accept actual
  summary column names and show unavailable optional QC metrics as NA.
- ONT failures use "Workflow failed"; Bulk retains "Nextflow failed".

Implementation complete. Validation passed: 33 workflow tests with the installed
native tools/R packages, including real Samtools/Modkit Stage 04 in both modes,
primary-only denominators despite supplementary/secondary records, joint and
5mC-only full R core/feature reports, weighted summary and lossless normalization
checks. Backend mode/schema/preflight/failure/recovery tests and 8 API contract
cases passed. Desktop tests, lint, typecheck and build passed. The source BAM now
passes the bounded probe. A broader project-test invocation was interrupted
after stalling; no full-suite result is claimed for this change.

[Awaiting manual testing] Reopen the saved project, choose 5mC only, validate/save
and rerun. No full downloaded-data pipeline run was launched during implementation.
