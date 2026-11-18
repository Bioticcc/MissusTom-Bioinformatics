# ONT reporting quality

Completed 2026-11-04 against the existing 13-sample human 5mC-only project.

The annotation-free report was a 763-byte PDF link index. Its plots mixed 195
reference contigs on one axis and duplicated 5mC/total-modified bars. Core QC
metrics and denominators were available but absent from the report.

Changes:

- Core R reporting now writes an offline HTML QC report with alignment-input
  yield/length metrics, coverage breadth/depth, modification-call accounting,
  browser previews/PDF downloads, scope notes, input/source checksums, and R
  session information. Unavailable measurements remain unavailable.
- Main-chromosome plots use readable horizontal labels, actual values and valid
  call denominators. Additional contigs remain in full and dedicated tables.
  Depth uses a labeled square-root axis. Per-sample identity/reference and
  measurement scope are retained on PDFs. Category labels/colors are readable
  and consistent; 5mC-only charts do not plot redundant total-modified bars or
  imply measured 5hmC. Raster previews use independently cloned plots and
  explicit chromosome labels after a device-repeat rendering issue was found.
- Modkit approximate failed-processing events are transcribed from the exact
  sample block in the original workflow log. They are explicitly separate from
  unique reads and failed/filtered CpG observations; rejection reasons are not
  inferred. An optional original instrument report remains separately linked.
- A manifest-scoped project overview and TSV summarize included samples only,
  without inferring biological groups or adding differential analysis. Backend
  artifact roots and desktop Results expose the overview; opening outputs uses
  the project root when it exists, preserving older layouts otherwise.
- --reports-only takes the project run lock, uses saved configurations, invokes
  Stage 05 only, and refreshes the project overview. It does not require raw
  input validation or rewrite configurations. Prior reports are archived.
- Removed fixed '74 pass modBAMs' wording from the annotated report template.

Native refresh completed successfully in
/mnt/20TB_A/Adam/MissusTom/ONToutputs. All 13 sample HTML reports, 52 PDF figures,
52 browser previews and the project overview were generated. The successful
final log is logs/ont-report-refresh-20261104T234920Z.log. All 651 published
Stage 01–04/configuration files retained their inode, size and nanosecond mtime;
no alignment or methylation calling ran. Prior Stage 05 outputs are under each
sample's tmp/stale_stage05/. Original run records/logs were preserved.

Validation:

- Complete ONT suite: 46 tests ran, 45 passed and one optional stock-Modkit
  comparison skipped. Final focused core-report tests: three passed (including
  human/mouse, joint/5mC-only, exact metrics, scope and link validation).
- Two report-only runner tests passed, proving no earlier stages/config rebuild
  and refusal under an active project lock.
- 41 backend adapter/source tests passed; all desktop tests, lint, typecheck,
  production build and bundle test passed. Scoped Python lint/format/mypy,
  shell syntax and diff checks passed.
- Native published-output verification checked 14 HTML documents, every local
  link, 52 PNG headers, checksum manifests, measured values, all 13 overview
  rows and preserved historical reports. Representative PDFs and PNGs were
  visually reviewed. A separate headless browser rendered the sample report
  and project overview; the sandboxed browser had crashed, so isolated host
  profiles under /tmp were used.
- During development, minimal fixtures were updated to the real global-summary
  contract and CSV parsing. The first native refresh stopped before replacing
  any report because of a shell-wrapper edit error; this was fixed and covered
  by the Stage 05 publish/reuse regression before successful refresh.

No release/package build, native Tauri GUI acceptance or upstream scientific
revalidation is claimed. Restart the development backend and reload the app
for the new project-level artifact category; regenerated HTML files can be
opened directly without rerunning the pipeline.

Material paths: lib/core_methylation_qc.R, lib/methylation_exploration.R,
lib/build_qc_overview.py, stages/05_methylation_exploration.sh, run_pipeline.py,
ONT tests (core report quality, runner, reference profiles), backend ONT adapter,
desktop runOutputs.ts/screens.behavior.test.mjs and the ONT workflow README.
Starting/ending commit: 595296ef7fc93d2376ba14b4bc2cc8f250f73e6a. No commit was
created; changes remain uncommitted. AGENT_TODO.md was not edited in this task.
