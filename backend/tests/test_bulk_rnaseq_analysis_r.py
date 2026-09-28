from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

KALLISTO_HEADER = "target_id\tlength\teff_length\test_counts\ttpm\n"


def _analysis_script_path() -> Path:
    return REPOSITORY_ROOT / "workflows" / "bulk_rnaseq" / "bin" / "bulk_rnaseq_analysis.R"


def _r_packages_available() -> bool:
    if shutil.which("Rscript") is None:
        return False
    probe = subprocess.run(
        [
            "Rscript",
            "-e",
            textwrap.dedent(
                """
                suppressPackageStartupMessages({
                  library(DESeq2)
                  library(tximport)
                  library(ggplot2)
                })
                """
            ).strip(),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return probe.returncode == 0


R_PACKAGES_AVAILABLE = _r_packages_available()
pytestmark = pytest.mark.skipif(
    not R_PACKAGES_AVAILABLE,
    reason="Rscript or required R packages (DESeq2, tximport, ggplot2) unavailable",
)


def _write_abundance(path: Path, rows: list[tuple[str, int, float]]) -> None:
    lines = [KALLISTO_HEADER]
    for target_id, est_counts, tpm in rows:
        lines.append(f"{target_id}\t500\t450\t{est_counts}\t{tpm}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def _write_table(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _run_analysis(
    tmp_path: Path,
    *,
    mapping_header: str,
    mapping_lines: list[str],
    sample_rows: list[str],
    comparison_rows: list[str],
    abundance_by_sample: dict[str, list[tuple[str, int, float]]],
    q_value: str = "0.05",
    lfc_threshold: str = "0",
    minimum_group_size: str = "2",
) -> subprocess.CompletedProcess[str]:
    mapping_path = tmp_path / "transcript_to_gene.tsv"
    _write_table(mapping_path, mapping_header, mapping_lines)
    samples_path = tmp_path / "samples.tsv"
    sample_header = "sample_id\tcondition\tintervention\tabundance_tsv"
    sample_lines: list[str] = []
    for row in sample_rows:
        sample_id = row.split("\t", 1)[0]
        abundance_path = tmp_path / "abundance" / f"{sample_id}.tsv"
        _write_abundance(abundance_path, abundance_by_sample[sample_id])
        sample_lines.append(f"{row}\t{abundance_path}")
    _write_table(samples_path, sample_header, sample_lines)

    comparisons_path = tmp_path / "comparisons.tsv"
    _write_table(
        comparisons_path,
        "comparison_id\tnumerator\tdenominator\tintervention",
        comparison_rows,
    )
    output_root = tmp_path / "analysis_output"
    output_root.mkdir()

    return subprocess.run(
        [
            "Rscript",
            str(_analysis_script_path()),
            str(samples_path),
            str(mapping_path),
            str(output_root),
            str(comparisons_path),
            q_value,
            lfc_threshold,
            minimum_group_size,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
        cwd=REPOSITORY_ROOT,
    )


def _read_contract(output_root: Path) -> list[dict[str, str]]:
    contract_path = output_root / "tables" / "summary" / "output_contract.tsv"
    lines = contract_path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append(dict(zip(header, values, strict=False)))
    return rows


def _contract_rows(
    output_root: Path,
    *,
    comparison_id: str,
    analysis_class: str,
    artifact: str,
) -> list[dict[str, str]]:
    return [
        row
        for row in _read_contract(output_root)
        if row["comparison_id"] == comparison_id
        and row["analysis_class"] == analysis_class
        and row["artifact"] == artifact
    ]


def _assert_generated_path_exists(output_root: Path, relative_path: str) -> None:
    target = output_root / relative_path
    assert target.is_file(), relative_path
    assert target.stat().st_size > 0


BASE_MAPPING = [
    "TX_A1\tG_ALPHA\tGeneAlpha\tprotein_coding",
    "TX_A2\tG_ALPHA\tGeneAlpha\tprotein_coding",
    "TX_B1\tG_BETA\tGeneBeta\tprotein_coding",
    "TX_C1\tG_GAMMA\tGeneGamma\tlncRNA",
]

BASE_SAMPLES = [
    "ctrl_a\tcontrol\t",
    "ctrl_b\tcontrol\t",
    "treat_a\ttreat\t",
    "treat_b\ttreat\t",
]

BASE_COMPARISON = ["cmp_treat_vs_control\ttreat\tcontrol\t"]

HIGH_CONTROL = [
    ("TX_A1", 120, 40.0),
    ("TX_A2", 110, 38.0),
    ("TX_B1", 20, 5.0),
    ("TX_C1", 18, 4.0),
]
HIGH_TREAT = [
    ("TX_A1", 18, 4.0),
    ("TX_A2", 22, 5.0),
    ("TX_B1", 130, 42.0),
    ("TX_C1", 125, 40.0),
]

EXPECTED_CLASS_ARTIFACTS = {
    "differential expression full results",
    "differential expression significant genes",
    "differential expression upregulated genes",
    "differential expression downregulated genes",
    "library-size normalized matrix",
    "rlog normalized matrix",
    "2D PCA plot",
    "scree plot",
    "3D PCA plot",
    "3D PCA HTML",
    "top-gene heatmap",
    "volcano plot",
    "MA plot",
    "p-value histogram",
    "adjusted p-value histogram",
    "fold-change density",
    "sample-distance heatmap",
    "DE counts by comparison plot",
    "DE totals by comparison plot",
    "comparison status table",
}


def test_all_gene_analysis_without_biotypes_column(tmp_path: Path) -> None:
    mapping_lines = [
        "TX_A1\tG_ALPHA\tGeneAlpha",
        "TX_A2\tG_ALPHA\tGeneAlpha",
        "TX_B1\tG_BETA\tGeneBeta",
    ]
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name",
        mapping_lines=mapping_lines,
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    output_root = tmp_path / "analysis_output"
    de_rows = _contract_rows(
        output_root,
        comparison_id="cmp_treat_vs_control",
        analysis_class="all-gene",
        artifact="differential expression full results",
    )
    assert de_rows and de_rows[0]["status"] == "generated"
    _assert_generated_path_exists(output_root, de_rows[0]["relative_path"])
    mrna_de = _contract_rows(
        output_root,
        comparison_id="cmp_treat_vs_control",
        analysis_class="mRNA",
        artifact="differential expression full results",
    )
    assert mrna_de and mrna_de[0]["status"] == "skipped"
    for analysis_class in ("mRNA", "lncRNA"):
        rows = [
            row
            for row in _read_contract(output_root)
            if row["comparison_id"] == "cmp_treat_vs_control"
            and row["analysis_class"] == analysis_class
        ]
        assert {row["artifact"] for row in rows} == EXPECTED_CLASS_ARTIFACTS
        assert {row["status"] for row in rows} == {"skipped"}
        assert all(row["rationale"] for row in rows)


def test_optional_mrna_lncrna_when_biotypes_present(tmp_path: Path) -> None:
    abundance = {
        "ctrl_a": [*HIGH_CONTROL, ("TX_D1", 24, 6.0)],
        "ctrl_b": [*HIGH_CONTROL, ("TX_D1", 22, 5.5)],
        "treat_a": [*HIGH_TREAT, ("TX_D1", 118, 36.0)],
        "treat_b": [*HIGH_TREAT, ("TX_D1", 122, 37.0)],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=[*BASE_MAPPING, "TX_D1\tG_DELTA\tGeneDelta\tlncRNA"],
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    output_root = tmp_path / "analysis_output"
    for analysis_class in ("mRNA", "lncRNA"):
        rows = _contract_rows(
            output_root,
            comparison_id="cmp_treat_vs_control",
            analysis_class=analysis_class,
            artifact="differential expression full results",
        )
        assert rows, analysis_class
        assert rows[0]["status"] == "generated"
        _assert_generated_path_exists(output_root, rows[0]["relative_path"])


def test_two_gene_analysis_skips_3d_pca_without_crashing(tmp_path: Path) -> None:
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=BASE_MAPPING[:3],
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    output_root = tmp_path / "analysis_output"
    skipped_3d = _contract_rows(
        output_root,
        comparison_id="cmp_treat_vs_control",
        analysis_class="all-gene",
        artifact="3D PCA plot",
    )
    assert skipped_3d and skipped_3d[0]["status"] == "skipped"
    assert "PC3" in skipped_3d[0]["rationale"] or "three principal" in skipped_3d[0]["rationale"]
    pca2 = _contract_rows(
        output_root,
        comparison_id="cmp_treat_vs_control",
        analysis_class="all-gene",
        artifact="2D PCA plot",
    )
    assert pca2 and pca2[0]["status"] == "generated"


def test_conflicting_transcript_mappings_fail(tmp_path: Path) -> None:
    mapping_lines = [
        "TX_A1\tG_ONE\tNameA\tprotein_coding",
        "TX_A1\tG_TWO\tNameA\tprotein_coding",
    ]
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=mapping_lines,
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode != 0
    assert "multiple gene_id" in (result.stderr or result.stdout)


@pytest.mark.parametrize(
    ("mapping_lines", "message"),
    [
        (["\tG_ONE\tNameA\tprotein_coding"], "empty transcript_id"),
        (["TX_A1\t\tNameA\tprotein_coding"], "empty gene_id"),
        (
            ["TX_A1\tG_ONE\tNameA\tprotein_coding", "TX_A1\tG_ONE\tNameB\tprotein_coding"],
            "conflicting gene_name",
        ),
        (
            ["TX_A1\tG_ONE\tNameA\tprotein_coding", "TX_A1\tG_ONE\tNameA\tlncRNA"],
            "conflicting gene_biotype",
        ),
        (
            [
                "TX_A1\tG_ONE\tNameA\tprotein_coding\tprocessed_transcript",
                "TX_A1\tG_ONE\tNameA\tprotein_coding\tprotein_coding",
            ],
            "conflicting transcript_biotype",
        ),
    ],
)
def test_mapping_validation_rejects_empty_or_conflicting_metadata(
    tmp_path: Path, mapping_lines: list[str], message: str
) -> None:
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    header = "transcript_id\tgene_id\tgene_name\tgene_biotype"
    if "transcript_biotype" in message:
        header += "\ttranscript_biotype"
    result = _run_analysis(
        tmp_path,
        mapping_header=header,
        mapping_lines=mapping_lines,
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )

    assert result.returncode != 0
    assert message in (result.stderr or result.stdout)


def test_identical_transcript_mapping_duplicates_are_deduplicated(tmp_path: Path) -> None:
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=[*BASE_MAPPING[:3], BASE_MAPPING[0]],
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_contrast_direction_preserves_numerator_over_denominator(tmp_path: Path) -> None:
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=BASE_MAPPING[:3],
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    de_path = (
        tmp_path
        / "analysis_output"
        / "differential_expression"
        / "all_genes"
        / "cmp_treat_vs_control"
        / "full_results.tsv"
    )
    lines = de_path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split("\t")
    gene_index = header.index("gene_id")
    lfc_index = header.index("log2FoldChange")
    by_gene = {}
    for line in lines[1:]:
        fields = line.split("\t")
        by_gene[fields[gene_index]] = float(fields[lfc_index])
    assert by_gene["G_BETA"] > 0
    assert by_gene["G_ALPHA"] < 0


def test_output_contract_matches_generated_and_skipped_files(tmp_path: Path) -> None:
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=BASE_MAPPING[:3],
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    output_root = tmp_path / "analysis_output"
    for row in _read_contract(output_root):
        assert row["status"] in {"generated", "skipped", "failed"}
        if row["status"] == "generated":
            _assert_generated_path_exists(output_root, row["relative_path"])
        if row["status"] == "skipped":
            assert row["rationale"]


def test_analysis_script_has_no_fixed_human_enst_ensg_assumptions() -> None:
    body = _analysis_script_path().read_text(encoding="utf-8")
    assert "ENST" not in body
    assert "ENSG" not in body


def test_mrna_class_skipped_with_single_protein_coding_gene(tmp_path: Path) -> None:
    mapping_lines = [
        "TX_A1\tG_ALPHA\tGeneAlpha\tprotein_coding",
        "TX_B1\tG_BETA\tGeneBeta\tlncRNA",
        "TX_C1\tG_GAMMA\tGeneGamma\tlncRNA",
    ]
    abundance = {
        "ctrl_a": [HIGH_CONTROL[index] for index in (0, 2, 3)],
        "ctrl_b": [HIGH_CONTROL[index] for index in (0, 2, 3)],
        "treat_a": [HIGH_TREAT[index] for index in (0, 2, 3)],
        "treat_b": [HIGH_TREAT[index] for index in (0, 2, 3)],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=mapping_lines,
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    output_root = tmp_path / "analysis_output"
    mrna_rows = [
        row
        for row in _read_contract(output_root)
        if row["comparison_id"] == "cmp_treat_vs_control" and row["analysis_class"] == "mRNA"
    ]
    assert {row["artifact"] for row in mrna_rows} == EXPECTED_CLASS_ARTIFACTS
    assert {row["status"] for row in mrna_rows} == {"skipped"}
    assert all(row["rationale"] for row in mrna_rows)
    lnc_rows = [
        row
        for row in _read_contract(output_root)
        if row["analysis_class"] == "lncRNA"
        and row["artifact"] == "differential expression full results"
    ]
    assert lnc_rows and lnc_rows[0]["status"] == "generated"


def test_optional_class_records_complete_skip_after_expression_filtering(
    tmp_path: Path,
) -> None:
    low_protein = ("TX_B1", 1, 0.1)
    abundance = {
        "ctrl_a": [HIGH_CONTROL[0], HIGH_CONTROL[1], low_protein, HIGH_CONTROL[3]],
        "ctrl_b": [HIGH_CONTROL[0], HIGH_CONTROL[1], low_protein, HIGH_CONTROL[3]],
        "treat_a": [HIGH_TREAT[0], HIGH_TREAT[1], low_protein, HIGH_TREAT[3]],
        "treat_b": [HIGH_TREAT[0], HIGH_TREAT[1], low_protein, HIGH_TREAT[3]],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=BASE_MAPPING,
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    rows = [
        row
        for row in _read_contract(tmp_path / "analysis_output")
        if row["analysis_class"] == "mRNA"
    ]
    assert {row["artifact"] for row in rows} == EXPECTED_CLASS_ARTIFACTS
    assert all(row["status"] == "skipped" for row in rows)
    assert all("expression filtering" in row["rationale"] for row in rows)


def test_heatmap_skip_is_recorded_when_too_few_genes_are_significant(
    tmp_path: Path,
) -> None:
    abundance = {
        "ctrl_a": HIGH_CONTROL[:3],
        "ctrl_b": HIGH_CONTROL[:3],
        "treat_a": HIGH_TREAT[:3],
        "treat_b": HIGH_TREAT[:3],
    }
    result = _run_analysis(
        tmp_path,
        mapping_header="transcript_id\tgene_id\tgene_name\tgene_biotype",
        mapping_lines=BASE_MAPPING[:3],
        sample_rows=BASE_SAMPLES,
        comparison_rows=BASE_COMPARISON,
        abundance_by_sample=abundance,
        q_value="1e-20",
        lfc_threshold="100",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    rows = _contract_rows(
        tmp_path / "analysis_output",
        comparison_id="cmp_treat_vs_control",
        analysis_class="all-gene",
        artifact="top-gene heatmap",
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "skipped"
    assert "Fewer than two genes" in rows[0]["rationale"]
