#!/usr/bin/env python3
"""Build the pinned ONT Modkit repair; never modify an installed environment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "backend/src/missus_tom/resources/modkit-repair"
OUTPUT = ROOT / "backend/build/analysis-tools/modkit-repair"
WORK = ROOT / "backend/build/modkit-repair"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    recipe = json.loads((RECIPE_DIR / "recipe.json").read_text())
    lock = RECIPE_DIR / "Cargo.lock"
    if digest(lock) != recipe["cargo_lock_sha256"]:
        raise RuntimeError("Modkit Cargo.lock differs from the reviewed recipe")
    WORK.mkdir(parents=True, exist_ok=True)
    archive = WORK / "source.tar.gz"
    if not archive.is_file() or digest(archive) != recipe["source_sha256"]:
        partial = archive.with_suffix(".partial")
        with (
            urllib.request.urlopen(recipe["source_url"], timeout=120) as response,
            partial.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        if digest(partial) != recipe["source_sha256"]:
            raise RuntimeError("Modkit source archive checksum mismatch")
        partial.replace(archive)
    source = WORK / ("modkit-" + recipe["source_commit"])
    with tarfile.open(archive) as bundle:
        for member in bundle:
            destination = (WORK / member.name).resolve()
            if not destination.is_relative_to(source.resolve()):
                raise RuntimeError("Unexpected Modkit archive path")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    bundle.extractfile(member) as incoming,
                    destination.open("wb") as output,
                ):
                    shutil.copyfileobj(incoming, output)
            else:
                raise RuntimeError("Unexpected link or special file in Modkit archive")
    shutil.copyfile(lock, source / "Cargo.lock")
    subprocess.run(
        [
            "cargo",
            "+" + recipe["rust_toolchain"],
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            str(source / "Cargo.toml"),
            "-p",
            "modkit",
            "-j",
            os.environ.get("MISSUS_TOM_MODKIT_BUILD_JOBS", "2"),
        ],
        check=True,
    )
    binary = source / "target/release/modkit"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, OUTPUT / "modkit")
    (OUTPUT / "modkit").chmod(0o755)
    shutil.copyfile(source / "LICENCE.txt", OUTPUT / "LICENCE.txt")
    shutil.copyfile(lock, OUTPUT / "Cargo.lock")
    manifest = {**recipe, "binary_sha256": digest(binary)}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {recipe['repair_id']}: {OUTPUT}")


if __name__ == "__main__":
    main()
