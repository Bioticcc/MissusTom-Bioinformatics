from __future__ import annotations

import csv
import re
from pathlib import Path

from missus_tom.models.metadata import MetadataCsvResult, MetadataRow

REQUIRED_COLUMNS = {"condition", "batch"}


def _normalize_sample_id(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^P50Large_", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^n(?=[0-9]+_(?:O|H)(?:$|_))", "", value, flags=re.IGNORECASE)
    value = value.replace("-", "_")
    return re.sub(r"_S[0-9]+$", "", value, flags=re.IGNORECASE)


def read_metadata_csv(path_value: str, sample_ids: list[str] | None = None) -> MetadataCsvResult:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Metadata CSV does not exist: {path}")
    if path.suffix.casefold() != ".csv":
        raise ValueError("Metadata file must be a .csv file")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Metadata CSV is empty or has no header row")
        normalized = {name.strip().casefold(): name for name in reader.fieldnames}
        sample_column = normalized.get("sampleid")
        missing = sorted(REQUIRED_COLUMNS - normalized.keys())
        if sample_column is None:
            missing.insert(0, "SampleID")
        if missing:
            raise ValueError(
                "Metadata CSV must include column titles: SampleID, condition, batch. "
                f"Missing: {', '.join(missing)}"
            )
        assert sample_column is not None

        rows: list[MetadataRow] = []
        seen: set[str] = set()
        replicate_column = normalized.get("biological_replicate") or normalized.get("patient")
        intervention_column = normalized.get("intervention")
        for line_number, raw in enumerate(reader, start=2):
            sample_id = (raw.get(sample_column) or "").strip()
            condition = (raw.get(normalized["condition"]) or "").strip()
            batch = (raw.get(normalized["batch"]) or "").strip() or None
            replicate = (
                (raw.get(replicate_column) or "").strip() or None if replicate_column else None
            )
            intervention = (
                (raw.get(intervention_column) or "").strip() or None
                if intervention_column
                else None
            )
            if not sample_id:
                raise ValueError(f"Metadata CSV row {line_number} has an empty SampleID value")
            if not condition:
                raise ValueError(f"Metadata CSV row {line_number} has an empty condition value")
            if sample_id in seen:
                raise ValueError(f"Metadata CSV contains duplicate SampleID: {sample_id}")
            seen.add(sample_id)
            rows.append(
                MetadataRow(
                    sample_id=sample_id,
                    condition=condition,
                    batch=batch,
                    biological_replicate=replicate,
                    intervention=intervention,
                )
            )

    if not rows:
        raise ValueError("Metadata CSV contains no sample rows")
    warnings: list[str] = []
    if replicate_column is None:
        warnings.append(
            "Biological replicates were not imported; assign them manually or add a "
            "biological_replicate column."
        )
    requested_samples = sample_ids or []
    unmatched_samples: list[str] = []
    matched_row_indexes: set[int] = set()
    matched_rows: list[MetadataRow] = []
    legacy_healthy_matches = 0
    rows_by_normalized: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        rows_by_normalized.setdefault(_normalize_sample_id(row.sample_id), []).append(index)
    chosen_by_normalized: dict[str, int] = {}
    duplicate_metadata_ids: list[str] = []
    for normalized_id, indexes in rows_by_normalized.items():
        chosen_by_normalized[normalized_id] = min(
            indexes,
            key=lambda index: (not rows[index].sample_id.lower().startswith("n"), index),
        )
        if len(indexes) > 1:
            duplicate_metadata_ids.append(normalized_id)
    if duplicate_metadata_ids:
        examples = ", ".join(sorted(duplicate_metadata_ids)[:8])
        more = len(duplicate_metadata_ids) - min(len(duplicate_metadata_ids), 8)
        warnings.append(
            f"{len(duplicate_metadata_ids)} metadata identifier(s) have legacy duplicates; "
            f"preferred leading-n rows when available: {examples}"
            + (f" (+{more} more)" if more else "")
        )

    normalized_project_ids = [_normalize_sample_id(sample_id) for sample_id in requested_samples]
    for sample_id, normalized_id in zip(requested_samples, normalized_project_ids, strict=True):
        row_index = chosen_by_normalized.get(normalized_id)
        if row_index is None and normalized_id.upper().endswith("_H_D1"):
            row_index = chosen_by_normalized.get(normalized_id[:-3])
            if row_index is not None:
                legacy_healthy_matches += 1
        if row_index is None:
            unmatched_samples.append(sample_id)
            continue
        matched_row_indexes.add(row_index)
        matched_rows.append(rows[row_index].model_copy(update={"matched_sample_id": sample_id}))

    if legacy_healthy_matches:
        warnings.append(
            f"Matched {legacy_healthy_matches} healthy _H_D1 sample(s) to _H metadata rows."
        )
    unused_rows = [
        row.sample_id for index, row in enumerate(rows) if index not in matched_row_indexes
    ]
    return MetadataCsvResult(
        path=str(path),
        rows=matched_rows if requested_samples else rows,
        warnings=warnings,
        unmatched_samples=unmatched_samples,
        unused_rows=unused_rows,
    )
