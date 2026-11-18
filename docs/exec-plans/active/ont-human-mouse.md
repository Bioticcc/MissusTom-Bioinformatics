# ONT human and mouse support

Authorized scope: explicit species/build selection, shared supported-reference
profiles, backend and standalone-runner gates, species-aware Stage 05 chromosome
handling and provenance, and focused synthetic regression checks. Preserve
modified-base semantics and independent per-sample processing. No real scientific
pipeline run is part of implementation validation.

Supported profiles: human GRCh38/hg38 and GRCh37/hg19; mouse GRCm38p6/GRCm38/mm10
and GRCm39/mm39. Chromosome naming: chr1 or 1 (consistent across references and
annotations); sex/mitochondrial chromosomes are optional in the supplied reference.

Status: implementation complete. [Awaiting manual testing] Native UI and real
human/mouse scientific acceptance remain manual checks.

Implemented: shared bundled reference profiles/checks; species/build and FAI
preflight/runner gates; main-chromosome propagation and stable restart settings;
species-aware core/feature reports; wizard selectors that clear stale references;
profile resources retained in custom pipeline revisions. Existing manifest
fields/schema are sufficient; no migration is required.

Validation:

- 67 focused backend reference/adapter/source/schema tests passed.
- Human and mouse API validation/plan tests passed.
- 19 workflow tests passed with the managed R environment, including synthetic
  human/mouse core PDF reports and actual feature chromosome-selection logic.
- Complete desktop tests, lint, typecheck, production build and bundle check passed.
- Backend lint/type checks and R/shell syntax checks passed.
- Full backend suite: 484 passed, 21 skipped, 1 cancellation-test failure
  (`test_docker_cleanup_failure_holds_admission_and_retry_can_finish`). The
  cancellation test passed on isolated rerun; no unrelated run-management code
  was changed for this task.

Manual checks: restart backend/app, select human and mouse profiles, verify
matching references and tags, then inspect real-data outputs and scientific
results. No real BAM pipeline run or packaged native acceptance was performed.

## Follow-up: optional minimap2 index

Implemented the user's request to generate `.mmi` when omitted. FASTA/FAI remain
required. Stage 01 prepares one project-owned `results/reference/reference.lr-hq.mmi`
with minimap2 `-x lr:hq -d`, using the alignment thread budget; samples/restarts
reuse the index only while source/tool/index fingerprints match. Adjacent JSON
records the preset, tool version and FASTA/index hashes. Index/metadata publishing
is atomic, generation is locked, symlinked write targets are rejected, and failed
builds do not become reusable completed indexes. Explicit supplied indexes are
still supported and must be readable/nonempty. Preflight and check-only do not
build indexes. Setup and the example manifest now make the optional input clear.

Validation: 55 focused backend checks, 4 API species/index-mode checks (native
containment mocked), 26 workflow tests including a real minimap2 build/alignment
on synthetic DNA, plus UI tests, typecheck/lint and production build. The installed
minimap2 used by that synthetic smoke check reported 2.30-r1287; this does not
establish acceptance of the locked 2.31 environment or full-genome Dorado runs.
The initial API attempt stalled in the systemd containment probe; input-contract
tests now isolate that independently tested host concern. No production containment
behavior was changed. Full-size reference indexing and native acceptance remain
[Awaiting manual testing].
