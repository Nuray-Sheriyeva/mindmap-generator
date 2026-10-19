"""Section-aware chunking with overlap and page references."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field

from .pdf.types import DocumentSection

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


class DocumentChunk(BaseModel):
    """A text chunk ready for the map step."""

    id: str
    index: int
    section_title: str
    section_level: int
    text: str
    source_pages: list[int] = Field(default_factory=list)
    token_estimate: int


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 characters per token)."""
    return max(1, math.ceil(len(text) / 4))


def _split_long_text(text: str, limit: int) -> list[str]:
    """Split a single oversized page/block at sentence, then word boundaries."""
    remaining = text.strip()
    parts: list[str] = []
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if cut < limit // 2:
            cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        part = remaining[: cut + (1 if remaining[cut : cut + 1] in ".!?" else 0)].strip()
        if part:
            parts.append(part)
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _tail(text: str, overlap: int) -> str:
    """Return a word-aligned tail for chunk overlap."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    if space > 0:
        tail = tail[space + 1 :]
    return tail.strip()


def chunk_document(
    sections: list[DocumentSection],
    *,
    max_chars: int = 6000,
    overlap_chars: int = 300,
) -> list[DocumentChunk]:
    """Split sections into chunks, preferring section boundaries.

    Long sections are split at paragraph/sentence boundaries. Overlap is
    carried between chunks of the same section, and every chunk keeps the
    pages its text came from.
    """
    if max_chars < 500:
        max_chars = 500
    chunks: list[DocumentChunk] = []
    for section in sections:
        if not section.text.strip():
            continue

        # Build sequential (page, text) pieces from the section's page blocks.
        pieces: list[tuple[int, str]] = []
        if section.blocks:
            for block in section.blocks:
                for part in _split_long_text(block.text, max_chars):
                    if part:
                        pieces.append((block.page, part))
        else:
            for part in _split_long_text(section.text, max_chars):
                pieces.append((section.page_start, part))

        current_text: list[str] = []
        current_pages: list[int] = []
        current_len = 0

        def flush(_section: DocumentSection = section) -> None:
            nonlocal current_text, current_pages, current_len
            text = "\n\n".join(current_text).strip()
            if not text:
                current_text, current_pages, current_len = [], [], 0
                return
            index = len(chunks)
            chunks.append(
                DocumentChunk(
                    id=f"chunk-{index}",
                    index=index,
                    section_title=_section.title,
                    section_level=_section.level,
                    text=text,
                    source_pages=sorted(set(current_pages)) or [_section.page_start],
                    token_estimate=estimate_tokens(text),
                )
            )
            current_text, current_pages, current_len = [], [], 0

        for page, piece in pieces:
            candidate_len = current_len + len(piece) + (2 if current_text else 0)
            if current_len and candidate_len > max_chars:
                previous_text = "\n\n".join(current_text).strip()
                flush()
                overlap = _tail(previous_text, overlap_chars)
                if overlap:
                    current_text = [overlap]
                    current_pages = [page]
                    current_len = len(overlap)
            if not current_text and not piece.strip():
                continue
            current_text.append(piece)
            current_pages.append(page)
            current_len += len(piece) + (2 if len(current_text) > 1 else 0)

        flush()

    # Guarantee unique ids even when sections produce no chunks.
    for index, chunk in enumerate(chunks):
        chunk.id = f"chunk-{index}"
        chunk.index = index
    return chunks
