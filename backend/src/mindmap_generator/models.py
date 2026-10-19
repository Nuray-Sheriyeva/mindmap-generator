"""Shared Pydantic models: final mind map schema and LLM output schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Final API / persistence schema
# ---------------------------------------------------------------------------
class MindMapNode(BaseModel):
    """One mind map node. ``children`` is empty for leaves."""

    id: str = ""
    label: str
    summary: str = ""
    source_pages: list[int] = Field(default_factory=list)
    children: list[MindMapNode] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    """Source document metadata included in every result."""

    filename: str
    pages: int
    language: str
    title: str | None = None


class MindMapMeta(BaseModel):
    """Generation metadata."""

    model: str
    generated_at: datetime
    node_count: int
    depth: int
    cache_hit: bool = False
    repair_attempts: int = 0
    generation_path: Literal["single_call", "map_reduce", "unknown"] = "unknown"
    output_language: str | None = None
    processing_ms: int = 0
    fixes: list[str] = Field(default_factory=list)


class MindMapResult(BaseModel):
    """Canonical result payload returned by the API and export endpoints."""

    document: DocumentInfo
    mindmap: MindMapNode
    meta: MindMapMeta


# ---------------------------------------------------------------------------
# Structured-output schemas given to the LLM (fixed depth: root + 3 levels)
# ---------------------------------------------------------------------------
class _LLMBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMLeafNode(_LLMBase):
    label: str
    summary: str
    source_pages: list[int]


class LLMLevel2Node(_LLMBase):
    label: str
    summary: str
    source_pages: list[int]
    children: list[LLMLeafNode]


class LLMLevel1Node(_LLMBase):
    label: str
    summary: str
    source_pages: list[int]
    children: list[LLMLevel2Node]


class LLMLevel0Node(_LLMBase):
    """The root object requested from the hierarchy prompt."""

    label: str
    summary: str
    source_pages: list[int]
    children: list[LLMLevel1Node]


class LLMConcept(_LLMBase):
    label: str
    summary: str
    source_pages: list[int]


class LLMChunkSummary(_LLMBase):
    summary: str
    key_concepts: list[LLMConcept]
    key_terms: list[str]


# ---------------------------------------------------------------------------
# Internal pipeline models
# ---------------------------------------------------------------------------
class ChunkSummary(BaseModel):
    """Map-step output attached to one document chunk."""

    chunk_id: str
    section_title: str
    section_level: int
    summary: str
    key_concepts: list[LLMConcept]
    key_terms: list[str]
    source_pages: list[int]


class GenerationOptions(BaseModel):
    """User-controlled generation knobs."""

    max_depth: int = 3
    max_branches: int = 6
    max_children: int = 6
    language: str | None = None


MindMapNode.model_rebuild()
