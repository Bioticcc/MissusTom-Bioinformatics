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

Keep verbose resolved configuration outside model context. Prefer the local
profile for configuration checks. The Docker profile remains available for
regression inspection:

```bash
nextflow config workflows/bulk_rnaseq -profile local > /tmp/missus-tom-nextflow.config
nextflow config workflows/bulk_rnaseq -profile docker > /tmp/missus-tom-nextflow.config
Rscript -e "parse(file='workflows/bulk_rnaseq/bin/bulk_rnaseq_analysis.R')"
```

For Dockerfile or R dependency changes, build the image after syntax/config
checks:

```bash
./scripts/build-analysis-image.sh
```

Real demo runs are final integration validation, not a routine source check.

`scripts/agent/synthetic-workflow-smoke.sh` is still a Docker-profile regression
check. It needs locally cached images and does not exercise the normal native
install. For a complete synthetic toolchain check with those cached images:

```bash
./scripts/agent/synthetic-workflow-smoke.sh
```

This generates its own small fixture under ignored `.agent-work/`, constrains
tasks to 2 CPUs / 4 GiB / one at a time, and verifies expected output categories
and absence of its own remaining containers. It does not read the demo/baseline
or pull Docker images. Nextflow may bootstrap its engine cache on the first run.

## Broad check

For the ONT module, run its synthetic contract tests and parse the scientific R
source without reading restricted BAMs or references:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s workflows/ont_analysis/tests
bash -n workflows/ont_analysis/lib/pipeline_common.sh
Rscript -e "invisible(parse(file='workflows/ont_analysis/lib/methylation_exploration.R'))"
```

Run `bash -n` separately for each changed ONT stage script. `--check-only` on the
runner verifies a supplied project's paths and local tools, not biological
equivalence or completion of downstream stages.

```bash
./scripts/check.sh
```

This runs Ruff lint/format, strict mypy, all backend tests, ESLint, frontend tests, TypeScript
checking, the Vite build, ONT synthetic contract tests, and ONT Bash syntax checks.
It intentionally excludes Rust, R execution, container builds,
and real Nextflow execution.

## Linux release packaging

Release packaging is Linux x86_64 only. The base `desktop/src-tauri/tauri.conf.json`
must remain development-safe and must not add `externalBin`; release-only sidecars
and workflow resources belong in `desktop/src-tauri/tauri.release.conf.json`.
The release overlay targets Debian packages only. The tag workflow publishes one
`ver<version>_Linux-x86_64_Ubuntu-Debian.zip`, containing exactly the `.deb`, its
`SHA256SUMS`, and `installation.md`; AppImage is not a current release format.

After creating `backend/.venv` with the `dev` and `packaging` extras and running
`npm ci` in `desktop/`, the CI-equivalent sequence is:

```bash
./scripts/check.sh
bash scripts/build-linux-sidecars.sh x86_64-unknown-linux-gnu
bash scripts/smoke-packaged-backend.sh \
  backend/dist/sidecars/missus-tom-backend-x86_64-unknown-linux-gnu \
  backend/build/sidecar-resources
cd desktop
npm run tauri:release
```

The smoke helper creates and removes its own temporary state directory, binds a
dedicated loopback port rather than port 8000, and stops only the backend it
started. It does not execute a workflow or demo. Do not run sidecar builds,
release bundling, package installation, or real/demo workflows on a machine
with an active ONT run unless the operator has explicitly confirmed that the
active run and its data are isolated. Never point smoke-test state, resource
roots, projects, or manifests at active ONT paths.
