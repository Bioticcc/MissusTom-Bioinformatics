# Missus Tom agent guide

## Project map

- Missus Tom is a local-only desktop workbench for human bulk RNA-seq and mouse
  ONT modified-base project setup, validation, and controlled execution.
- `backend/src/missus_tom/`: FastAPI application, typed models, services, and
  pipeline adapters. Entry point: `missus_tom.main:app`.
- `backend/tests/`: Python API, service, manifest, and schema tests.
- `desktop/src/`: React/TypeScript UI. Entry points: `main.tsx` and `App.tsx`.
- `desktop/src-tauri/`: Rust host commands and Tauri packaging configuration.
- `schemas/project-manifest.schema.json`: versioned JSON manifest contract.
- `workflows/bulk_rnaseq/`: Nextflow DSL2 workflow, resource policy, container
  definition, and R analysis. Its nested `AGENTS.md` adds scientific rules.
- `workflows/ont_analysis/`: manifest-driven native-tool runner, restartable ONT
  stages, weighted summary helpers, and mouse methylation exploration.
- `scripts/`: setup, development, demo-preparation, and agent utilities.
- `docs/`: architecture, baseline evidence, migration decisions, and open
  scientific questions.
- Runtime data belongs outside Git. Generated `work/`, `results/`, caches,
  dependency trees, and build outputs are ignored and are not source.

## Sources of truth

- Product setup, supported demo, and operator commands: `README.md`.
- Implemented component ownership and request flow: `docs/mvp_architecture.md`.
- Baseline evidence and unresolved scientific choices:
  `docs/baseline_pipeline_inventory.md` and `docs/open_questions.md`.
- Current migration decisions: `docs/pipeline_migration_map.md`.
- API behavior: `backend/src/missus_tom/api/routes.py` and the Pydantic models.
- Manifest contract: keep the JSON schema, Pydantic model, TypeScript types, and
  synthetic example aligned; `backend/tests/test_schema.py` checks part of this.
- Workflow contract: `workflows/bulk_rnaseq/README.md`, `main.nf`,
  `nextflow.config`, and `conf/resources.config`.
- Validation commands and escalation order: `docs/agent/WORKFLOWS.md`.

## Investigation rules

- Start with this guide, `git status --short`, and the nearest authoritative
  manifest or document. Use `scripts/agent/repo-map.sh` only when a broader map
  is useful.
- Search exact symbols, paths, keys, errors, imports, and call sites before
  opening large files. Prefer `rg` when available, then `git grep` or bounded
  `find`.
- Read only relevant ranges. Do not rescan understood files unless the task or
  repository state changed.
- Prefer documented contracts and manifests over rediscovering facts in code.
- Do not inspect dependency trees, lockfiles, generated files, caches, build
  output, workflow results, FASTQs, reference data, or large logs unless the
  task specifically requires them.
- Follow dependencies only far enough to make or verify the requested change.
  Stop exploring once sufficient evidence exists to act safely.
- Before editing, state the likely owner, affected contracts/callers, expected
  behavior, and cheapest relevant validation.

## Change rules

- Keep changes focused; do not mix opportunistic refactors with the task.
- The external `../BulkRnaSeq` scientific baseline is read-only. Never modify or
  run it as part of ordinary Missus Tom development.
- The external `../ONTAnalysis` baseline is also read-only. Keep ONT's mouse
  references and modified-base semantics separate from human bulk RNA-seq.
- Do not add biological inference from filenames. User-confirmed manifest data
  is authoritative for conditions, comparisons, and other biology.
- Preserve the local-only security boundary: fixed argument arrays,
  `shell=False`, loopback networking, validated paths, and no data upload.
- Do not weaken the restricted-demo execution gates without an explicit task
  and corresponding contract tests.
- Update API envelopes/types and the manifest representations together when a
  shared contract changes.
- Do not hand-edit generated output or dependency lockfiles. Use the owning tool
  when a dependency change intentionally requires a lock update.
- Do not commit bioinformatics inputs, references, results, provenance maps,
  workflow work directories, logs, or credentials.

## Validation ladder

Use the cheapest check likely to catch the failure, then expand as risk warrants:

1. Syntax or formatter/static checks for the changed files.
2. The narrowest relevant pytest file/test, frontend check, Rust check, or
   workflow parse/config check.
3. The complete affected component checks.
4. `./scripts/check.sh` for all non-Rust application checks.
5. `cargo check` or `npm run tauri build -- --no-bundle` for native changes.
6. Container builds or real Nextflow/demo execution only when workflow behavior
   requires them; these are expensive and depend on local restricted resources.

See `docs/agent/WORKFLOWS.md` for exact commands. Do not claim checks that were
not run, and distinguish dependency/environment failures from code failures.

## Command-output hygiene

- Prefer quiet or concise flags when they preserve actionable errors and exit
  status.
- Do not print successful repetitive output. Preserve failing test/task names,
  error context, and important warnings.
- Redirect verbose output to a task-specific file under `/tmp` when useful;
  report its path and inspect only relevant excerpts.
- Never hide a failure behind `head`, `tail`, or a pipeline that loses its exit
  code. Use bounded display only after the complete output is safely retained.
- Await long commands efficiently instead of repeatedly polling unchanged state.
- Summarize successful validation rather than reproducing logs.

## Session behavior

- Begin normal tasks with targeted orientation, not a recursive repository scan.
- Continue an existing session while its task and context remain directly
  relevant; use a clean session for a substantially different task.
- For substantial multi-session work, keep a concise checkpoint at
  `docs/exec-plans/active/<task-name>.md`. Move it to `completed/` only when it
  retains useful history; otherwise delete it. Do not load unrelated old plans.
- Keep stable facts in canonical docs or this guide and transient state in an
  active plan or `/tmp`. Never promote temporary failures, process IDs, paths,
  or branch state into persistent instructions.
- Do not create documentation for facts already obvious from code or already
  authoritative elsewhere.
- Report what changed, decisions that matter, validation run, and unresolved
  risks; omit routine command transcripts.
