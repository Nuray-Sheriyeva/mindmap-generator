"""LangGraph pipeline state and stage metadata."""

from __future__ import annotations

from typing import TypedDict

STAGE_SEQUENCE: tuple[str, ...] = (
    "parse_pdf",
    "chunk_document",
    "summarize_chunks",
    "build_hierarchy",
    "validate_and_repair",
    "finalize",
)

STAGE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "parse_pdf": "Parsing PDF",
    "chunk_document": "Chunking document",
    "summarize_chunks": "Summarizing sections",
    "build_hierarchy": "Building hierarchy",
    "validate_and_repair": "Validating mind map",
    "finalize": "Finalizing",
}


def stage_position(stage: str | None) -> tuple[int, int, float]:
    """Return ``(stage_index, total_stages, progress)`` for a stage name."""
    total = len(STAGE_SEQUENCE)
    if not stage or stage not in STAGE_SEQUENCE:
        return 0, total, 0.0
    index = STAGE_SEQUENCE.index(stage) + 1
    return index, total, round(index / total, 3)


class PipelineState(TypedDict, total=False):
    """Mutable state passed between graph nodes.

    Large binary input is only present at the start; the final result is the
    only value consumed by the API layer.
    """

    job_id: str
    pdf_bytes: bytes
    filename: str
    options: dict
    document: dict
    sections: list[dict]
    chunks: list[dict]
    chunk_summaries: list[dict]
    draft: dict
    mindmap: dict
    validation_errors: list[str]
    fixes: list[str]
    warnings: list[str]
    repair_attempts: int
    finalize_ready: bool
    generation_path: str
    started_at: float
    result: dict
