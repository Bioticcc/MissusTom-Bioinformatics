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
    assert model.schema_version == "1.0.0"
