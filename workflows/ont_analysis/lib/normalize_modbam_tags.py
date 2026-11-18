"""Rename legacy modification tags in a streamed BAM, preserving every record.

Do not change modification codes, probabilities, implicit/explicit modes, read
sequences or alignments. MN is preserved when present and never invented.
"""

from __future__ import annotations

import argparse
import subprocess
from contextlib import suppress


def normalize_line(line: str) -> str:
    if line.startswith("@"):
        return line
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 11:
        raise ValueError("Malformed SAM record during modification-tag normalization")
    tags = fields[11:]
    for legacy, modern in (("Mm", "MM"), ("Ml", "ML")):
        old = [i for i, tag in enumerate(tags) if tag.startswith(legacy + ":")]
        new = [i for i, tag in enumerate(tags) if tag.startswith(modern + ":")]
        if len(old) + len(new) > 1:
            raise ValueError(f"Duplicate or ambiguous {modern}/{legacy} tags")
        if old:
            tags[old[0]] = modern + tags[old[0]][2:]
    return "\t".join(fields[:11] + tags) + "\n"


def normalize(samtools: str, output: str) -> None:
    decoder = subprocess.Popen([samtools, "view", "-h", "-"], stdout=subprocess.PIPE, text=True)
    encoder = subprocess.Popen(
        [samtools, "view", "-b", "-o", output, "-"], stdin=subprocess.PIPE, text=True
    )
    try:
        assert decoder.stdout is not None and encoder.stdin is not None
        for line in decoder.stdout:
            encoder.stdin.write(normalize_line(line))
        encoder.stdin.close()
        if decoder.wait() != 0 or encoder.wait() != 0:
            raise ValueError("Samtools failed during modification-tag normalization")
    finally:
        for stream in (decoder.stdout, encoder.stdin):
            with suppress(OSError):
                if stream is not None and not stream.closed:
                    stream.close()
        for process in (decoder, encoder):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samtools", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    normalize(args.samtools, args.output)
