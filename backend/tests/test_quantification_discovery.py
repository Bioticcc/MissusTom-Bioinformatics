from __future__ import annotations

from pathlib import Path

from missus_tom.models.discovery import PairingStatus
from missus_tom.services.quantifications import discover_quantifications

KALLISTO_HEADER = "target_id\tlength\teff_length\test_counts\ttpm\n"


def write_abundance(root: Path, sample_id: str, *, header: str = KALLISTO_HEADER) -> Path:
    destination = root / sample_id / "abundance.tsv"
    destination.parent.mkdir(parents=True)
    destination.write_text(header, encoding="utf-8")
    return destination


def test_discovers_kallisto_tables_as_samples(tmp_path: Path) -> None:
    first = write_abundance(tmp_path, "Control 1")
    second = write_abundance(tmp_path, "Treated_1")

    result = discover_quantifications(str(tmp_path))

    assert result.total_files == 2
    assert {sample.sample_id for sample in result.samples} == {"Control_1", "Treated_1"}
    assert {sample.abundance_tsv for sample in result.samples} == {str(first), str(second)}
    assert all(sample.pairing_status == PairingStatus.QUANTIFIED for sample in result.samples)


def test_warns_when_abundance_header_is_not_kallisto(tmp_path: Path) -> None:
    write_abundance(tmp_path, "sample", header="wrong\theader\n")

    result = discover_quantifications(str(tmp_path))

    assert any("expected Kallisto" in warning for warning in result.samples[0].warnings)


def test_empty_quantification_directory_is_reported(tmp_path: Path) -> None:
    result = discover_quantifications(str(tmp_path))

    assert result.samples == []
    assert any("No Kallisto" in warning for warning in result.warnings)
