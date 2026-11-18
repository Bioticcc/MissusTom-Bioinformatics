#!/usr/bin/env python3
"""Bounded primary-read modBAM probe; Modkit performs later full tag validation.

Accept both separate and combined MM modification codes. Do not require every
mapped read to contain calls, or decode an entire BAM to inspect its first read.
"""

from __future__ import annotations

import subprocess
import sys


def inspect_tags(samtools: str, bam: str, max_records: int = 1000) -> tuple[bool, str]:
    process = subprocess.Popen(
        [samtools, "view", "-F", "2308", bam],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    observed: set[str] = set()
    scanned = 0
    try:
        assert process.stdout is not None
        for index, line in enumerate(process.stdout):
            tags = line.rstrip("\n").split("\t")[11:]
            scanned += 1
            observed.update(tag.split(":", 1)[0] for tag in tags)
            fields = line.rstrip("\n").split("\t")
            has_mm = any(tag.startswith(("MM:Z:", "Mm:Z:")) for tag in tags)
            has_ml = any(tag.startswith(("ML:B:C,", "Ml:B:C,")) for tag in tags)
            mn = next((tag[5:] for tag in tags if tag.startswith("MN:i:")), None)
            if has_mm and has_ml and len(fields) >= 11:
                if mn is not None and (not mn.isdigit() or int(mn) != len(fields[9])):
                    return False, f"MN tag disagrees with sequence length in {bam}"
                return True, "Modification tags found on a primary mapped read"
            if index + 1 >= max_records:
                break
        if "Mm" in observed or "Ml" in observed:
            reason = (
                "Incomplete legacy Mm/Ml tags were found; both modification locations "
                "and probabilities are required."
            )
        else:
            reason = "No primary mapped record with MM/ML (or legacy Mm/Ml) tags was found."
        return False, f"{reason} Inspected {scanned} mapped records from {bam}."
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def check_tags(samtools: str, bam: str, max_records: int = 1000) -> bool:
    return inspect_tags(samtools, bam, max_records)[0]


if __name__ == "__main__":
    valid, message = inspect_tags(*sys.argv[1:])
    if not valid:
        sys.exit(message)
