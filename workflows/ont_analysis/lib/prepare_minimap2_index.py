"""Build and safely reuse a project-owned lr:hq minimap2 reference index."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def reject_symlinks(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError(f"Generated reference path contains a symbolic link: {path}")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def prepare_index(fasta: Path, index: Path, minimap2: Path, threads: int) -> Path:
    if threads < 1:
        raise ValueError("Indexing threads must be positive")
    fasta = fasta.resolve(strict=True)
    minimap2 = minimap2.resolve(strict=True)
    if not fasta.is_file() or not fasta.stat().st_size:
        raise ValueError("Reference FASTA must be a nonempty regular file")
    metadata = index.with_suffix(index.suffix + ".json")
    lock = index.with_suffix(index.suffix + ".lock")
    for path in (index, metadata, lock):
        reject_symlinks(path)
    index.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Reference index is being prepared by another run") from exc
        version = subprocess.run(
            [str(minimap2), "--version"], check=True, capture_output=True, text=True, timeout=15
        ).stdout.strip()
        signature = {
            "schema_version": 1,
            "preset": "lr:hq",
            "fasta": fingerprint(fasta),
            "minimap2": fingerprint(minimap2),
            "minimap2_version": version,
        }
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if (
                isinstance(saved, dict)
                and saved.get("signature") == signature
                and index.is_file()
                and index.stat().st_size > 0
                and saved.get("index") == fingerprint(index)
            ):
                print(f"REFERENCE INDEX: reusing {index}", flush=True)
                return index
        except (OSError, ValueError):
            pass
        print(
            f"REFERENCE INDEX: building {index} from {fasta} (lr:hq, {threads} threads)", flush=True
        )
        temporary_index = None
        temporary_metadata = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".index-partial-", dir=index.parent)
            os.close(descriptor)
            temporary_index = Path(name)
            fasta_digest = sha256(fasta)
            subprocess.run(
                [
                    str(minimap2),
                    "-x",
                    "lr:hq",
                    "-t",
                    str(threads),
                    "-d",
                    str(temporary_index),
                    str(fasta),
                ],
                check=True,
            )
            if not temporary_index.is_file() or not temporary_index.stat().st_size:
                raise ValueError("Minimap2 did not produce a nonempty reference index")
            if fingerprint(fasta) != signature["fasta"]:
                raise ValueError("Reference FASTA changed during index preparation; retry the run")
            if fingerprint(minimap2) != signature["minimap2"]:
                raise ValueError("Minimap2 changed during index preparation; retry the run")
            index_digest = sha256(temporary_index)
            temporary_index.replace(index)
            payload = {
                "signature": signature,
                "fasta_sha256": fasta_digest,
                "index_sha256": index_digest,
                "index": fingerprint(index),
            }
            descriptor, name = tempfile.mkstemp(prefix=".metadata-partial-", dir=index.parent)
            temporary_metadata = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as writer:
                json.dump(payload, writer, indent=2)
                writer.write("\n")
            temporary_metadata.replace(metadata)
            print(f"REFERENCE INDEX: ready {index}", flush=True)
            return index
        finally:
            for path in (temporary_index, temporary_metadata):
                if path is not None:
                    path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fasta", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--minimap2", required=True, type=Path)
    parser.add_argument("--threads", required=True, type=int)
    args = parser.parse_args()
    try:
        prepare_index(args.fasta, args.index, args.minimap2, args.threads)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Reference index preparation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
