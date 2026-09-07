# Agent validation workflows

Use the narrowest relevant command first. Commands assume the repository root
unless a `cd` is shown. Full demo execution is deliberately excluded: it is
expensive and requires restricted local data and references.

## Backend

For changed Python files, run lint and format checks from `backend/` so Ruff
loads `pyproject.toml`:

```bash
cd backend
.venv/bin/ruff check src tests ../scripts/prepare_human_demo.py
.venv/bin/ruff format --check src tests ../scripts/prepare_human_demo.py
```

Run the narrowest relevant test, then type-check when source contracts changed:

```bash
cd backend
.venv/bin/pytest -q tests/test_schema.py
.venv/bin/mypy src
```

Replace the test path with the owning file or `file.py::test_name`. Use
`.venv/bin/pytest -q` for the complete backend suite.

## Desktop web UI

```bash
cd desktop
npm run lint
npm test
npm run typecheck
npm run build
```

Lint first, then run the dependency-free request-coordination/API regression tests
and type-check. The build is the broader web check and writes only
ignored `desktop/dist/` output.

## Tauri host

For Rust command or Tauri host changes:

```bash
cargo check --quiet --manifest-path desktop/src-tauri/Cargo.toml
```

Use the broader native build only when packaging/integration risk warrants it:

```bash
cd desktop
npm run tauri build -- --no-bundle
```

## Manifest contract

When changing the JSON Schema, Pydantic manifest model, TypeScript manifest
types, or synthetic example, validate all affected representations, then run:

```bash
cd backend
.venv/bin/pytest -q tests/test_schema.py tests/test_manifest.py tests/test_api.py
```

## Nextflow and R workflow

Keep verbose resolved configuration outside model context:

```bash
nextflow config workflows/bulk_rnaseq -profile docker > /tmp/missus-tom-nextflow.config
Rscript -e "parse(file='workflows/bulk_rnaseq/bin/full_human_analysis.R')"
```

For Dockerfile or R dependency changes, build the image after syntax/config
checks:

```bash
./scripts/build-analysis-image.sh
```

Real demo runs are final integration validation, not a routine source check.

For a complete synthetic toolchain check with locally cached Docker images:

```bash
./scripts/agent/synthetic-workflow-smoke.sh
```

This generates its own small fixture under ignored `.agent-work/`, constrains
tasks to 2 CPUs / 4 GiB / one at a time, and verifies expected output categories
and absence of its own remaining containers. It does not read the demo/baseline
or pull Docker images. Nextflow may bootstrap its engine cache on the first run.

## Broad check

```bash
./scripts/check.sh
```

This runs Ruff lint/format, strict mypy, all backend tests, ESLint, frontend tests, TypeScript
checking, and the Vite build. It intentionally excludes Rust, container builds,
and real Nextflow execution.
