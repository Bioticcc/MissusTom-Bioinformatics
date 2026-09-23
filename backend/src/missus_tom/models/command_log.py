from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CommandLogChunk(BaseModel):
    text: str
    next_offset: int
    bytes_available: int
    truncated: bool = False
    last_output_at: datetime | None = None
