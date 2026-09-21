#!/usr/bin/env python3
"""Create deterministic, valid PNG icons required by the Linux Tauri bundle."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            border = min(x, y, size - 1 - x, size - 1 - y) < max(1, size // 16)
            row.extend((35, 83, 131, 255) if border else (236, 245, 250, 255))
        rows.append(b"\0" + bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress(b"".join(rows), level=9)
    ) + chunk(b"IEND", b"")


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "desktop" / "src-tauri" / "icons"
    destination.mkdir(parents=True, exist_ok=True)
    for name, size in {"32x32.png": 32, "128x128.png": 128, "128x128@2x.png": 256}.items():
        (destination / name).write_bytes(png(size))


if __name__ == "__main__":
    main()
