"""LangGraph pipeline state and stage metadata."""

from __future__ import annotations

from typing import TypedDict

STAGE_SEQUENCE: tuple[str, ...] = (
    "parse_pdf",
    "classify_sections",
    "chunk_document",
    "extract_concepts",
    "build_hierarchy",
    "validate_and_repair",
    "finalize",
)

STAGE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "parse_pdf": "Parsing PDF",
    "classify_sections": "Classifying sections",
    "chunk_document": "Chunking content",
    "extract_concepts": "Extracting concepts",
    "build_hierarchy": "Clustering ideas",
    "validate_and_repair": "Validating map",
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
    """Mutable state passed between graph nodes."""

    job_id: str
    pdf_bytes: bytes
    filename: str
    options: dict
    document: dict
    sections: list[dict]
    objectives: list[str]
    page_texts: dict[int, str]
    chunks: list[dict]
    concepts: list[dict]
    cluster: dict
    mindmap: dict
    validation_errors: list[str]
    repair_errors_by_id: dict[str, list[str]]
    repair_target: str
    fixes: list[str]
    warnings: list[str]
    repair_attempts: int
    finalize_ready: bool
    generation_path: str
    started_at: float
    result: dict
