from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ChunkText:
    index: int
    content: str
    char_count: int


class ChunkingService:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = min(chunk_overlap, chunk_size // 2)

    def chunk(self, text: str) -> list[ChunkText]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []

        chunks: list[ChunkText] = []
        start = 0
        index = 0

        while start < len(normalized):
            end = min(start + self.chunk_size, len(normalized))
            if end < len(normalized):
                split_at = normalized.rfind(" ", start, end)
                if split_at > start + self.chunk_size // 2:
                    end = split_at

            content = normalized[start:end].strip()
            if content:
                chunks.append(ChunkText(index=index, content=content, char_count=len(content)))
                index += 1

            if end >= len(normalized):
                break

            start = max(0, end - self.chunk_overlap)
            while start < len(normalized) and normalized[start].isspace():
                start += 1

        return chunks

