"""Shared validation for Bulk RNA-seq experimental-design settings."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from missus_tom.models.manifest import Comparison, SampleRecord

INDEPENDENT_DESIGN = "independent"
PAIRED_DESIGN = "paired"


def experimental_design_type(parameters: Mapping[str, object]) -> str:
    """Return the explicit setting, retaining independent legacy behavior."""
    value = parameters.get("experimental_design_type", INDEPENDENT_DESIGN)
    if value not in {INDEPENDENT_DESIGN, PAIRED_DESIGN}:
        raise ValueError("experimental_design_type must be independent or paired")
    return value


def batch_adjustment_enabled(parameters: Mapping[str, object]) -> bool:
    """Return the opt-in batch setting, retaining unadjusted legacy behavior."""
    value = parameters.get("adjust_for_batch_effects", False)
    if not isinstance(value, bool):
        raise ValueError("adjust_for_batch_effects must be true or false")
    return value


def statistical_model(design_type: str, adjust_for_batch_effects: bool) -> str:
    factors: list[str] = []
    if adjust_for_batch_effects:
        factors.append("batch")
    if design_type == PAIRED_DESIGN:
        factors.append("biological_replicate")
    factors.append("condition")
    return "~ " + " + ".join(factors)


def _matrix_rank(matrix: list[list[int]]) -> int:
    """Calculate exact rank for a small 0/1 design matrix without NumPy."""
    rows = [[float(value) for value in row] for row in matrix]
    rank = 0
    columns = len(rows[0]) if rows else 0
    for column in range(columns):
        pivot = next((index for index in range(rank, len(rows)) if rows[index][column] != 0), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        divisor = rows[rank][column]
        rows[rank] = [value / divisor for value in rows[rank]]
        for index, row in enumerate(rows):
            if index != rank and row[column] != 0:
                factor = row[column]
                rows[index] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(row, rows[rank], strict=True)
                ]
        rank += 1
    return rank


def batch_design_errors(
    samples: Iterable[SampleRecord],
    comparisons: Iterable[Comparison],
    design_type: str,
) -> list[str]:
    """Reject missing or non-identifiable batch-adjusted comparison models."""
    errors: list[str] = []
    all_samples = list(samples)
    for comparison in comparisons:
        selected = [
            sample
            for sample in all_samples
            if sample.condition in {comparison.numerator, comparison.denominator}
            and (
                not comparison.intervention
                or sample.covariates.get("intervention") == comparison.intervention
            )
        ]
        missing = sorted(sample.sample_id for sample in selected if not sample.batch)
        if missing:
            errors.append(
                f"{comparison.comparison_id}: missing batch assignment for " + ", ".join(missing)
            )
            continue
        factor_values: list[tuple[str, list[str]]] = [
            ("batch", [sample.batch or "" for sample in selected])
        ]
        if design_type == PAIRED_DESIGN:
            if any(not sample.biological_replicate for sample in selected):
                continue
            factor_values.append(
                ("biological_replicate", [sample.biological_replicate for sample in selected])
            )
        factor_values.append(("condition", [sample.condition for sample in selected]))
        if len(set(factor_values[0][1])) < 2:
            errors.append(
                f"{comparison.comparison_id}: batch adjustment requires at least two batches"
            )
            continue
        columns: list[list[int]] = [[1] for _ in selected]
        for _, values in factor_values:
            levels = sorted(set(values))
            for level in levels[1:]:
                for row, value in zip(columns, values, strict=True):
                    row.append(int(value == level))
        if len(selected) <= len(columns[0]) or _matrix_rank(columns) != len(columns[0]):
            errors.append(
                f"{comparison.comparison_id}: batch, subject, and condition are confounded "
                "or leave no residual degrees of freedom"
            )
    return errors


def paired_design_errors(
    samples: Iterable[SampleRecord],
    comparisons: Iterable[Comparison],
    minimum_group_size: int,
) -> list[str]:
    """Describe invalid paired assignments for every requested comparison."""
    errors: list[str] = []
    all_samples = list(samples)
    for comparison in comparisons:
        selected = [
            sample
            for sample in all_samples
            if sample.condition in {comparison.numerator, comparison.denominator}
            and (
                not comparison.intervention
                or sample.covariates.get("intervention") == comparison.intervention
            )
        ]
        missing = sorted(sample.sample_id for sample in selected if not sample.biological_replicate)
        if missing:
            errors.append(
                f"{comparison.comparison_id}: missing biological replicate ID for "
                + ", ".join(missing)
            )
            continue
        assignments: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for sample in selected:
            assignments[sample.biological_replicate][sample.condition].append(sample.sample_id)
        duplicate = sorted(
            f"{subject} ({group}: {', '.join(sample_ids)})"
            for subject, groups in assignments.items()
            for group, sample_ids in groups.items()
            if len(sample_ids) != 1
        )
        if duplicate:
            errors.append(
                f"{comparison.comparison_id}: a subject has multiple samples in one condition: "
                + "; ".join(duplicate)
            )
            continue
        incomplete = sorted(
            subject
            for subject, groups in assignments.items()
            if set(groups) != {comparison.numerator, comparison.denominator}
        )
        if incomplete:
            errors.append(
                f"{comparison.comparison_id}: subjects must have exactly one sample in both "
                f"conditions: {', '.join(incomplete)}"
            )
            continue
        if len(assignments) < minimum_group_size:
            errors.append(
                f"{comparison.comparison_id}: requires at least "
                f"{minimum_group_size} paired subjects"
            )
    return errors
