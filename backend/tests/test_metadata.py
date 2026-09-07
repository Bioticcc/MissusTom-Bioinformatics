from __future__ import annotations

from pathlib import Path

import pytest

from missus_tom.services.metadata import read_metadata_csv


def test_metadata_csv_imports_required_and_optional_fields(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "SampleID,condition,batch,biological_replicate,notes\n"
        "sample_01,HFD,run_1,mouse_01,kept\n"
        "sample_02,ICD,run_2,mouse_02,kept\n",
        encoding="utf-8",
    )

    result = read_metadata_csv(str(metadata))

    assert [row.sample_id for row in result.rows] == ["sample_01", "sample_02"]
    assert result.rows[0].condition == "HFD"
    assert result.rows[0].batch == "run_1"
    assert result.rows[0].biological_replicate == "mouse_01"
    assert result.rows[0].intervention is None
    assert result.warnings == []
    assert result.unmatched_samples == []


def test_metadata_csv_requires_named_columns(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text("SampleID,condition\nsample_01,HFD\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SampleID, condition, batch"):
        read_metadata_csv(str(metadata))


def test_metadata_csv_rejects_legacy_sample_header(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "sample,condition,batch\nsample_01,HFD,run_1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SampleID, condition, batch"):
        read_metadata_csv(str(metadata))


def test_metadata_csv_rejects_duplicate_samples(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "SampleID,condition,batch\nsample_01,HFD,run_1\nsample_01,ICD,run_2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate SampleID: sample_01"):
        read_metadata_csv(str(metadata))


def test_original_human_metadata_columns_and_ids_are_supported(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "Patient,SampleID,Condition,Intervention,Batch\n115,115_H,H,H,1\n119,119_O_D1,OD1,D,1\n",
        encoding="utf-8",
    )

    result = read_metadata_csv(
        str(metadata),
        ["115-H_D1", "P50Large_119-O_D1_S20"],
    )

    rows = {row.matched_sample_id: row for row in result.rows}
    assert rows["115-H_D1"].biological_replicate == "115"
    assert rows["P50Large_119-O_D1_S20"].intervention == "D"
    assert result.unmatched_samples == []
    assert result.unused_rows == []


def test_legacy_duplicate_metadata_can_fill_old_and_new_sample_names(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "Patient,SampleID,Condition,Intervention,Batch\n"
        "107,107_O_W12,OW12,D,1\n"
        "107,n107_O_W12,OW12,D,5\n",
        encoding="utf-8",
    )

    result = read_metadata_csv(
        str(metadata),
        ["107-O_W12", "P50Large_107_O_W12"],
    )

    assert len(result.rows) == 2
    assert {row.matched_sample_id for row in result.rows} == {
        "107-O_W12",
        "P50Large_107_O_W12",
    }
    assert all(row.batch == "5" for row in result.rows)
    assert any("preferred leading-n rows" in warning for warning in result.warnings)
