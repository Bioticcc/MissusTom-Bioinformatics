from __future__ import annotations

import os
import re
from pathlib import Path

from missus_tom.models.discovery import (
    DiscoveredQuantification,
    PairingStatus,
    ProposedSample,
    QuantificationDiscoveryResult,
)

UNSAFE_SAMPLE_CHARACTER = re.compile(r"[^A-Za-z0-9._-]+")
EXPECTED_COLUMNS = {"target_id", "length", "eff_length", "est_counts", "tpm"}


def _safe_sample_id(value: str) -> str:
    normalized = UNSAFE_SAMPLE_CHARACTER.sub("_", value.strip()).strip("._-")
    return normalized or "unnamed_sample"


def _find_abundance_tables(root: Path, recursive: bool) -> tuple[list[Path], list[str]]:
    tables: list[Path] = []
    warnings: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            warnings.append(f"Could not scan {directory}: {exc.strerror or exc}")
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    warnings.append(f"Skipped symbolic link: {entry.path}")
                elif entry.is_dir(follow_symlinks=False) and recursive:
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name == "abundance.tsv":
                    tables.append(Path(entry.path))
            except OSError as exc:
                warnings.append(f"Could not inspect {entry.path}: {exc.strerror or exc}")
    return sorted(tables, key=lambda path: str(path).casefold()), warnings


def has_kallisto_header(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as handle:
            columns = set(handle.readline().rstrip("\r\n").split("\t"))
    except (OSError, UnicodeError):
        return False
    return EXPECTED_COLUMNS.issubset(columns)


def discover_quantifications(
    directory: str,
    recursive: bool = True,
) -> QuantificationDiscoveryResult:
    root = Path(directory).expanduser().resolve(strict=False)
    if not root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")

    tables, warnings = _find_abundance_tables(root, recursive)
    samples: list[ProposedSample] = []
    files: list[DiscoveredQuantification] = []
    seen_ids: set[str] = set()
    total_bytes = 0
    for table in tables:
        sample_id = _safe_sample_id(table.parent.name)
        sample_warnings: list[str] = []
        if sample_id in seen_ids:
            sample_warnings.append("Duplicate proposed sample identifier; rename it during review")
        seen_ids.add(sample_id)
        if not has_kallisto_header(table):
            sample_warnings.append(
                "The file does not have the expected Kallisto abundance.tsv header"
            )
        try:
            size = table.stat().st_size
        except OSError:
            size = 0
            sample_warnings.append("Could not read file size")
        total_bytes += size
        files.append(
            DiscoveredQuantification(sample_id=sample_id, path=str(table), size_bytes=size)
        )
        samples.append(
            ProposedSample(
                sample_id=sample_id,
                abundance_tsv=str(table),
                pairing_status=PairingStatus.QUANTIFIED,
                warnings=sample_warnings,
            )
        )

    if not tables:
        warnings.append("No Kallisto abundance.tsv files were found")
    return QuantificationDiscoveryResult(
        directory=str(root),
        samples=samples,
        files=files,
        warnings=warnings,
        total_files=len(files),
        total_bytes=total_bytes,
    )
