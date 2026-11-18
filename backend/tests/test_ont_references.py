from pathlib import Path

import pytest

from missus_tom.services.ont_references import ont_main_chromosomes, supported_ont_reference


@pytest.mark.parametrize(
    "organism,build,count",
    [
        ("Homo sapiens", "GRCh38", 22),
        ("Homo sapiens", "hg38", 22),
        ("Homo sapiens", "GRCh37", 22),
        ("Homo sapiens", "hg19", 22),
        ("Mus musculus", "GRCm38p6", 19),
        ("Mus musculus", "GRCm38", 19),
        ("Mus musculus", "mm10", 19),
        ("Mus musculus", "GRCm39", 19),
        ("Mus musculus", "mm39", 19),
    ],
)
@pytest.mark.parametrize("prefix", ["chr", ""])
def test_species_builds_and_naming_styles(tmp_path: Path, organism, build, count, prefix):
    fai = tmp_path / "reference.fai"
    names = [f"{prefix}{i}" for i in range(1, count + 1)] + [f"{prefix}X"]
    fai.write_text("".join(f"{name}\t100\t0\t100\t101\n" for name in names))
    assert supported_ont_reference(organism, build)
    assert ont_main_chromosomes(fai, organism, build) == names


@pytest.mark.parametrize(
    "organism,build",
    [
        ("Homo sapiens", "GRCm38p6"),
        ("Mus musculus", "hg38"),
        ("Danio rerio", "GRCz11"),
        ("Homo sapiens", "unknown"),
    ],
)
def test_reject_mismatched_or_unsupported_species_builds(organism, build):
    assert not supported_ont_reference(organism, build)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "chr1\t100\n",
        "chr1\tNaN\t0\t100\t101\n",
        "chr1\t0\t0\t100\t101\n",
        "chr1\t100\t0\t100\t99\n",
        "chr1\t100\t0\t100\t101\n" * 2,
    ],
)
def test_invalid_or_incomplete_fai_blocks_execution(tmp_path: Path, content):
    fai = tmp_path / "reference.fai"
    fai.write_text(content)
    with pytest.raises(ValueError):
        ont_main_chromosomes(fai, "Homo sapiens", "GRCh38")


def test_human_mouse_reference_mismatch_is_rejected(tmp_path: Path):
    fai = tmp_path / "reference.fai"
    fai.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 23)))
    assert "chr22" in ont_main_chromosomes(fai, "Homo sapiens", "GRCh38")
    with pytest.raises(ValueError, match="human autosomes"):
        ont_main_chromosomes(fai, "Mus musculus", "GRCm38p6")
    fai.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)))
    with pytest.raises(ValueError, match="all 22"):
        ont_main_chromosomes(fai, "Homo sapiens", "GRCh38")
