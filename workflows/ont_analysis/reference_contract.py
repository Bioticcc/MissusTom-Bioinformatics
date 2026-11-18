"""Pure reference checks shared by the backend and standalone ONT runner."""
from __future__ import annotations

import json
from pathlib import Path


PROFILES = json.loads(Path(__file__).with_name("reference_profiles.json").read_text())


def reference_profile(organism: str, reference: str) -> dict:
    if not isinstance(organism, str) or not isinstance(reference, str):
        raise ValueError("ONT organism and reference_genome must be strings")
    profile = PROFILES.get(organism)
    if profile is None or reference not in profile["references"]:
        supported = "; ".join(
            f"{species}: {', '.join(item['references'])}" for species, item in PROFILES.items()
        )
        raise ValueError(f"Unsupported ONT species/reference pair. Supported: {supported}")
    return profile


def main_chromosomes(fai: Path, organism: str, reference: str) -> list[str]:
    """Validate FAI structure and return main contigs using its exact naming style."""
    profile = reference_profile(organism, reference)
    lengths: dict[str, int] = {}
    with fai.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                raise ValueError("Reference FAI must contain five tab-separated columns")
            try:
                length, offset, bases, width = map(int, fields[1:5])
            except ValueError as exc:
                raise ValueError("Reference FAI contains invalid numeric fields") from exc
            if not fields[0] or fields[0] in lengths or length <= 0 or offset < 0:
                raise ValueError("Reference FAI contains duplicate contigs or invalid lengths/offsets")
            if bases <= 0 or width < bases:
                raise ValueError("Reference FAI contains invalid line widths")
            lengths[fields[0]] = length
    count = profile["autosomes"]
    for prefix in ("chr", ""):
        autosomes = [f"{prefix}{number}" for number in range(1, count + 1)]
        if not set(autosomes).issubset(lengths):
            continue
        if organism == "Mus musculus" and any(
            f"{prefix}{number}" in lengths for number in range(20, 23)
        ):
            raise ValueError("Mouse reference FAI contains human autosomes 20-22")
        optional = [f"{prefix}X", f"{prefix}Y", "chrM" if prefix else "MT"]
        if not prefix and "M" in lengths and "MT" not in lengths:
            optional[-1] = "M"
        return autosomes + [name for name in optional if name in lengths]
    raise ValueError(
        f"Reference FAI must contain all {count} {organism} autosomes, named chr1..chr{count} "
        f"or 1..{count}; use matching chromosome names in annotations"
    )
