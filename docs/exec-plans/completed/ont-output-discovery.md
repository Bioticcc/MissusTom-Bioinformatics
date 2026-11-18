# ONT output discovery

The completed 13-sample run wrote 52 PDFs and detailed outputs under
`results/samples/<sample>/`. Project save still created empty numbered stage
folders at the root, while Results displayed only Bulk RNA-seq categories.

Implemented:

- ONT project creation now creates shared samples/reference directories.
- Results displays ONT-specific artifact groups and resets filters when changing
  runs. Jobs and Results open the published sample tree when indexed files show
  that layout. Legacy ONT and Bulk retain their existing folder destinations;
  Jobs can still open the root when artifact indexing is unavailable.
- Mounted UI regressions exercise actual ONT file visibility, directory opening,
  filter reset, Bulk, legacy ONT, and API-unavailable fallback. A project-save
  regression verifies the new layout and preserves existing historical files.

The user's completed ONToutputs project was repaired under its exclusive
`.active-run.lock`: seven known empty placeholders were removed with rmdir only,
nonempty directories were preserved, and all 52 PDFs remained. No analysis files
were rewritten or analysis rerun. The root now contains reference/ and samples/.

Validation: 35 backend project/ONT tests passed outside the sandbox; the initial
new fixture omitted its ONT adapter and was corrected. The sandbox async test
run stalled and was terminated. All desktop tests (including eight mounted
screen tests), lint, typecheck, production build and bundle checks passed;
scoped Python lint/format/mypy and diff checks passed. No native GUI acceptance
or release packaging is claimed. The backend must load the updated project-save
code before creating new projects; current desktop source changes require the
usual app reload/rebuild to appear in the user's running UI.

Starting/ending commit: 595296ef7fc93d2376ba14b4bc2cc8f250f73e6a; no commit created.
Changes remain uncommitted. Material source paths: projects.py, runOutputs.ts,
Jobs.tsx, Results.tsx, test_ont_analysis_adapter.py, screens.behavior.test.mjs,
and the ONT workflow README.
