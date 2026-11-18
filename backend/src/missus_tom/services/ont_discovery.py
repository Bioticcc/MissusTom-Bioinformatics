from __future__ import annotations

import os
import re
from pathlib import Path

from missus_tom.models.discovery import (
    DiscoveredOntBam,
    OntDiscoveryResult,
    PairingStatus,
    ProposedSample,
)


def discover_ont_bams(directory: str, recursive: bool = True) -> OntDiscoveryResult:
    """Propose one sample per regular BAM; biological grouping requires review."""
    root = Path(directory).expanduser()
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError("ONT input directory must not contain symbolic links")
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")

    pending = [root]
    files: list[DiscoveredOntBam] = []
    warnings: list[str] = []
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            warnings.append(f"Skipped symbolic link: {entry.path}")
                        elif entry.is_dir(follow_symlinks=False) and recursive:
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".bam"):
                            files.append(
                                DiscoveredOntBam(
                                    path=entry.path,
                                    size_bytes=entry.stat(follow_symlinks=False).st_size,
                                )
                            )
                    except OSError as exc:
                        warnings.append(f"Could not inspect {entry.path}: {exc.strerror or exc}")
        except OSError as exc:
            warnings.append(f"Could not scan {folder}: {exc.strerror or exc}")

    files.sort(key=lambda item: item.path)
    samples: list[ProposedSample] = []
    used: set[str] = set()
    for item in files:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(item.path).stem).strip("._-")
        base = (base or "ont_sample")[:100]
        sample_id = base
        suffix = 2
        while sample_id in used:
            sample_id = f"{base}_{suffix}"
            suffix += 1
        used.add(sample_id)
        samples.append(
            ProposedSample(
                sample_id=sample_id, ont_bam_files=[item.path], pairing_status=PairingStatus.SINGLE
            )
        )
    warnings.insert(
        0,
        "One sample is proposed per BAM. Review assignments before applying. "
        "Combine BAMs only when they belong to the same biological sample. "
        "Indexes (.bai) are ignored; BAM contents and reference compatibility "
        "are checked separately during validation.",
    )
    return OntDiscoveryResult(
        directory=str(root),
        samples=samples,
        files=files,
        warnings=warnings,
        total_files=len(files),
        total_bytes=sum(item.size_bytes for item in files),
    )
