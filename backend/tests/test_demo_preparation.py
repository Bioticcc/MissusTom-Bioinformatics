from __future__ import annotations

import gzip
import runpy
from pathlib import Path
from typing import Any


def _write_fastq(path: Path, mate: int) -> None:
    with gzip.open(path, "wt", encoding="ascii") as handle:
        for index in range(1, 4):
            handle.write(f"@source-{index}/{mate}\nACGT\n+\nIIII\n")


def test_subset_rewrites_headers_and_preserves_sources(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_human_demo.py"
    module: dict[str, Any] = runpy.run_path(str(script))
    subset_pair = module["_subset_pair"]

    source_r1 = tmp_path / "source_R1.fastq.gz"
    source_r2 = tmp_path / "source_R2.fastq.gz"
    destination_r1 = tmp_path / "derived" / "DEMO_H_01_R1.fastq.gz"
    destination_r2 = tmp_path / "derived" / "DEMO_H_01_R2.fastq.gz"
    _write_fastq(source_r1, 1)
    _write_fastq(source_r2, 2)
    source_hashes = module["_sha256"](source_r1), module["_sha256"](source_r2)

    count, digest_r1, digest_r2 = subset_pair(
        source_r1,
        source_r2,
        destination_r1,
        destination_r2,
        "DEMO_H_01",
        2,
    )

    assert count == 2
    assert digest_r1 == module["_sha256"](destination_r1)
    assert digest_r2 == module["_sha256"](destination_r2)
    assert source_hashes == (module["_sha256"](source_r1), module["_sha256"](source_r2))
    with gzip.open(destination_r1, "rt", encoding="ascii") as handle:
        records = handle.read().splitlines()
    assert records == [
        "@DEMO_H_01:000000001/1",
        "ACGT",
        "+",
        "IIII",
        "@DEMO_H_01:000000002/1",
        "ACGT",
        "+",
        "IIII",
    ]
    assert destination_r1.stat().st_mode & 0o777 == 0o600
    assert destination_r2.stat().st_mode & 0o777 == 0o600
