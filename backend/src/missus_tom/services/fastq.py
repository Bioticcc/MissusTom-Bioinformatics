from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from missus_tom.models.discovery import (
    DiscoveredFastq,
    FastqDiscoveryResult,
    PairingStatus,
    ProposedSample,
    ReadAssignment,
)

FASTQ_EXTENSION = re.compile(r"(?i)\.(?:fastq|fq)(?:\.gz)?$")
READ_MARKER = re.compile(r"(?i)(?P<separator>[_\-.])R(?P<read>[12])(?=$|[_\-.])")
SHORT_READ_MARKER = re.compile(r"(?i)(?P<separator>[_\-.])(?P<read>[12])$")
LOOSE_READ_MARKER = re.compile(r"(?i)R[12]")
LANE_MARKER = re.compile(r"(?i)(?:^|[_\-.])L(?P<lane>\d{3})(?=$|[_\-.])")
LANE_TOKEN = re.compile(r"(?i)(^|[_\-.])L\d{3}(?=$|[_\-.])")
UNSAFE_SAMPLE_CHARACTER = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ParsedName:
    sample_id: str
    pairing_key: str
    read: int | None
    lane: str | None
    ambiguous: bool = False
    warning: str | None = None


@dataclass
class PairBucket:
    r1: list[str] = field(default_factory=list)
    r2: list[str] = field(default_factory=list)
    lanes: set[str] = field(default_factory=set)


def _without_extension(filename: str) -> str:
    return FASTQ_EXTENSION.sub("", filename)


def _safe_sample_id(value: str) -> str:
    value = LANE_TOKEN.sub(r"\1", value)
    value = value.strip("._- ")
    value = UNSAFE_SAMPLE_CHARACTER.sub("_", value)
    value = re.sub(r"[_\-.]{2,}", "_", value).strip("._-")
    return value or "unnamed_sample"


def parse_fastq_name(filename: str) -> ParsedName:
    stem = _without_extension(filename)
    lane_match = LANE_MARKER.search(stem)
    lane = f"L{lane_match.group('lane')}" if lane_match else None

    markers = list(READ_MARKER.finditer(stem))
    if not markers:
        markers = list(SHORT_READ_MARKER.finditer(stem))

    if len(markers) > 1:
        return ParsedName(
            sample_id=_safe_sample_id(stem),
            pairing_key=stem,
            read=None,
            lane=lane,
            ambiguous=True,
            warning=f"{filename}: more than one read marker was found",
        )

    if len(markers) == 1:
        marker = markers[0]
        left = stem[: marker.start()]
        pairing_key = f"{left}{stem[marker.end() :]}"
        return ParsedName(
            sample_id=_safe_sample_id(left),
            pairing_key=pairing_key.casefold(),
            read=int(marker.group("read")),
            lane=lane,
        )

    if LOOSE_READ_MARKER.search(stem):
        return ParsedName(
            sample_id=_safe_sample_id(stem),
            pairing_key=stem,
            read=None,
            lane=lane,
            ambiguous=True,
            warning=f"{filename}: an R1/R2-like token is present but not safely delimited",
        )

    return ParsedName(
        sample_id=_safe_sample_id(stem),
        pairing_key=stem.casefold(),
        read=None,
        lane=lane,
    )


def _walk_fastq_files(root: Path, recursive: bool) -> tuple[list[os.DirEntry[str]], list[str]]:
    files: list[os.DirEntry[str]] = []
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
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        pending.append(Path(entry.path))
                    continue
                if entry.is_file(follow_symlinks=False) and FASTQ_EXTENSION.search(entry.name):
                    files.append(entry)
            except OSError as exc:
                warnings.append(f"Could not inspect {entry.path}: {exc.strerror or exc}")

    files.sort(key=lambda entry: entry.path.casefold())
    return files, warnings


def discover_fastqs(directory: str, recursive: bool = True) -> FastqDiscoveryResult:
    root = Path(directory).expanduser().resolve(strict=False)
    if not root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")

    entries, warnings = _walk_fastq_files(root, recursive)
    discovered: list[DiscoveredFastq] = []
    unassigned: list[str] = []
    paired: dict[str, dict[str, PairBucket]] = defaultdict(dict)
    singles: dict[str, list[str]] = defaultdict(list)
    sample_warnings: dict[str, list[str]] = defaultdict(list)
    sample_lanes: dict[str, set[str]] = defaultdict(set)
    total_bytes = 0

    for entry in entries:
        parsed = parse_fastq_name(entry.name)
        try:
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            size = 0
            warnings.append(f"Could not read file size: {entry.path}")
        total_bytes += size

        if parsed.ambiguous:
            unassigned.append(entry.path)
            if parsed.warning:
                warnings.append(parsed.warning)
            discovered.append(
                DiscoveredFastq(
                    path=entry.path,
                    size_bytes=size,
                    read=ReadAssignment.AMBIGUOUS,
                    lane=parsed.lane,
                )
            )
            continue

        if parsed.lane:
            sample_lanes[parsed.sample_id].add(parsed.lane)

        if parsed.read is None:
            singles[parsed.sample_id].append(entry.path)
            assignment = ReadAssignment.SINGLE
        else:
            bucket = paired[parsed.sample_id].setdefault(parsed.pairing_key, PairBucket())
            if parsed.lane:
                bucket.lanes.add(parsed.lane)
            if parsed.read == 1:
                bucket.r1.append(entry.path)
                assignment = ReadAssignment.R1
            else:
                bucket.r2.append(entry.path)
                assignment = ReadAssignment.R2

        discovered.append(
            DiscoveredFastq(
                path=entry.path,
                size_bytes=size,
                read=assignment,
                lane=parsed.lane,
            )
        )

    proposals: list[ProposedSample] = []
    for sample_id in sorted(set(paired) | set(singles), key=str.casefold):
        r1_files: list[str] = []
        r2_files: list[str] = []
        local_warnings = sample_warnings[sample_id]
        status = PairingStatus.PAIRED

        for pairing_key in sorted(paired.get(sample_id, {})):
            bucket = paired[sample_id][pairing_key]
            if len(bucket.r1) > 1 or len(bucket.r2) > 1:
                status = PairingStatus.AMBIGUOUS
                local_warnings.append(
                    f"Duplicate assignments for pairing key '{pairing_key}' require review"
                )
            elif not bucket.r1 or not bucket.r2:
                if status != PairingStatus.AMBIGUOUS:
                    status = PairingStatus.UNMATCHED
                missing = "R1" if not bucket.r1 else "R2"
                local_warnings.append(f"Missing {missing} mate for pairing key '{pairing_key}'")
            r1_files.extend(sorted(bucket.r1))
            r2_files.extend(sorted(bucket.r2))

        single_files = sorted(singles.get(sample_id, []))
        if single_files and paired.get(sample_id):
            status = PairingStatus.AMBIGUOUS
            local_warnings.append(
                "Paired and unmarked single-end files share this sample identifier"
            )
        elif single_files:
            status = PairingStatus.SINGLE
        r1_files.extend(single_files)

        if len(single_files) > 1 and not sample_lanes[sample_id]:
            local_warnings.append("Multiple unmarked FASTQs were grouped; confirm lane assignments")

        proposals.append(
            ProposedSample(
                sample_id=sample_id,
                r1_files=r1_files,
                r2_files=r2_files,
                lanes=sorted(sample_lanes[sample_id]),
                pairing_status=status,
                warnings=local_warnings,
            )
        )

    if not entries:
        warnings.append("No supported FASTQ files were found")
    if unassigned:
        warnings.append(f"{len(unassigned)} FASTQ file(s) require manual assignment")

    return FastqDiscoveryResult(
        directory=str(root),
        samples=proposals,
        files=discovered,
        unassigned_files=sorted(unassigned),
        warnings=warnings,
        total_files=len(entries),
        total_bytes=total_bytes,
    )
