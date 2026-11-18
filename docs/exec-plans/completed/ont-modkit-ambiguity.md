# Stage 04 Modkit crash investigation

The 15:01 run passed Stage 03 and selected `5mc_only`. Stage 04's check-tags
reported no errors; the crash occurs in `modkit summary` during threshold
sampling, before pileup. `modkit_all_context_summary.txt` is empty. This is not
the prior coverage or measurement-mode failure.

Confirmed with installed Modkit 0.6.4 and real Samtools: a single mapped reverse
read containing N, MM:C+m and ML probabilities panics at the exact reported
`base_mods_adapter.rs:80` location (exit 101). An A/C/G/T reverse control and an
N-containing forward control succeed. Fixtures are under
`/tmp/ont-modkit-ambiguity-x3op7l09`. These fixtures demonstrate the defect class;
the exact offending record in the user's complete BAM has not been isolated.
Bounded scans of 5,000 leading reverse primaries and 374 records in selected
regions did not encounter an ambiguous symbol. No full-data rerun was launched.

Primary upstream evidence:

- https://github.com/nanoporetech/modkit/issues/719 reports the same panic with
  the downloaded megalodon/remora dataset family.
- https://github.com/nanoporetech/modkit/issues/668 gives independent forward,
  reverse, leading-ambiguity and soft-clip fixtures, including silent loss of
  downstream valid calls in generic/optimized processing.
- https://github.com/nanoporetech/modkit/pull/597 is still open in the inspected
  source. Its initial patch does not cover every downstream-state case; the
  related closed PR #714 contains additional regression oracles.

Status: repaired and ready for the operator to rerun the existing project.

Implemented a source-pinned Modkit build (PR #714 head
`bb20328778b2a5e3f0f815b36af2ae09c1df7ae7`), a generated Cargo lock with
hts-sys 2.2.0, checksum-verified build assets, installer overlay into inactive
candidates, runtime identity checks and run provenance. Sidecar builds stage the
repair and its license; the scientific CI includes native ambiguity fixtures.
The conda package lock remains enforced. Stage 04 invalidates cached outputs
when its Modkit executable changes.

Local acceptance:

- Reproducible build script completed using Rust 1.98.0.
- 32 focused dependency/runtime tests passed; mypy and targeted lint passed.
- 52 ONT adapter/source/run/API contract tests passed outside the sandbox
  (the sandbox run stalled and was stopped).
- 40 complete ONT workflow tests passed with real tools/R. The added canonical
  comparison also passed: joint m/h output matches stock 0.6.4 byte-for-byte
  for both workers. Ambiguity regression cases cover forward/reverse IUPAC,
  leading ambiguity and soft-clipped overrun with exact downstream call counts.
- Installed a fresh private runtime through the real installer job
  `5a26a14d-f155-4656-b6f0-9111909caa67`; all tool/R/conda/repair checks passed
  before atomic activation. The preceding environment is retained.
- Active runtime reports no lock/repair mismatches, missing tools or Setup
  requirements.
- Repeated the exact failing summary command on the user's aligned BAM:
  completed successfully, 1,556,074 reads and 71,395,310 passing calls.
- Bounded real-data CpG pileup of chr1:1-1,000,000 completed with 1,994 rows
  and 1,493 modified calls. Its 148 failed-processing records match exactly
  the 148 primary records with empty MM and empty ML arrays; no modification
  identities or unmodified calls were invented for those records.

Diagnostic outputs are under `/tmp/missus-modkit-build/`. The existing project,
source BAMs and saved results were not rewritten by diagnostics. Restart the
development backend to load the new validation/provenance code, retain
`5mc_only`, and rerun the existing project. Full multi-sample workflow/GUI
acceptance and packaged release smoke testing remain outside these checks.
