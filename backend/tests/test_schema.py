from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from missus_tom.models.manifest import ProjectManifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_json_schema_is_valid_and_accepts_synthetic_example() -> None:
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas" / "project-manifest.schema.json").read_text(encoding="utf-8")
    )
    example = json.loads(
        (REPOSITORY_ROOT / "examples" / "synthetic-project-manifest.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    model = ProjectManifest.model_validate(example)
    assert model.schema_version == "1.1.0"
    assert model.reference_mode is not None
    assert model.reference_mode.value == "build"


def test_json_schema_enforces_bulk_reference_modes() -> None:
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas" / "project-manifest.schema.json").read_text(encoding="utf-8")
    )
    example = json.loads(
        (REPOSITORY_ROOT / "examples" / "synthetic-project-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    missing_mode = {**example}
    missing_mode.pop("reference_mode")
    assert list(validator.iter_errors(missing_mode))

    build_with_index = json.loads(json.dumps(example))
    build_with_index["reference_resources"]["kallisto_index"] = "/references/transcripts.idx"
    assert list(validator.iter_errors(build_with_index))

    analysis_only = json.loads(json.dumps(example))
    analysis_only["parameters"]["start_stage"] = "analysis"
    analysis_only["reference_resources"].pop("transcriptome_fasta")
    validator.validate(analysis_only)
