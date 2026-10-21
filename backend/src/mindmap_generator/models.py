"""Shared Pydantic models: canonical mind map schema and LLM output schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeKind = Literal["root", "branch", "leaf"]
SectionKind = Literal["content", "objectives", "activities", "reference", "scaffold"]


# ---------------------------------------------------------------------------
# Final API / persistence schema (schema_version = 2)
# ---------------------------------------------------------------------------
class MindMapNode(BaseModel):
    """One map node.

    ``root``/``branch`` nodes are pure categories: label and children only.
    ``leaf`` nodes carry the visible, grounded explanation and source pages.
    """

    id: str = ""
    kind: NodeKind
    label: str
    explanation: str | None = None
    source_pages: list[int] = Field(default_factory=list)
    children: list[MindMapNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_shape(self) -> MindMapNode:
        if self.kind == "leaf":
            if self.children:
                raise ValueError("leaf nodes cannot have children")
            if not (self.explanation or "").strip():
                raise ValueError("leaf nodes require a non-empty explanation")
        else:
            if self.explanation:
                raise ValueError("root/branch nodes must not carry an explanation")
        return self


class DocumentInfo(BaseModel):
    """Source document metadata included in every result."""

    filename: str
    pages: int
    language: str
    title: str | None = None


class MindMapMeta(BaseModel):
    """Generation metadata."""

    schema_version: int = 2
    model: str
    generated_at: datetime
    node_count: int
    leaf_count: int = 0
    branch_count: int = 0
    depth: int
    cache_hit: bool = False
    repair_attempts: int = 0
    generation_path: str = "concept_clustering"
    output_language: str | None = None
    processing_ms: int = 0
    fixes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MindMapResult(BaseModel):
    """Canonical result payload returned by the API and export endpoints."""

    document: DocumentInfo
    mindmap: MindMapNode
    meta: MindMapMeta


# ---------------------------------------------------------------------------
# Structured-output schemas
# ---------------------------------------------------------------------------
class _LLMBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMConcept(_LLMBase):
    """A grounded concept card extracted from one source chunk."""

    term: str
    explanation: str
    evidence: str
    source_pages: list[int]


class LLMConceptList(_LLMBase):
    concepts: list[LLMConcept]


class LLMRepairedConcept(_LLMBase):
    id: str
    term: str
    explanation: str
    evidence: str
    source_pages: list[int]


class LLMRepairedConceptList(_LLMBase):
    concepts: list[LLMRepairedConcept]


class LLMClusterGroup(_LLMBase):
    """A subgroup of concept IDs inside one category.

    Use an empty label when the category does not need a sub-category.
    """

    label: str
    concept_ids: list[str]


class LLMClusterCategory(_LLMBase):
    label: str
    groups: list[LLMClusterGroup]


class LLMClusterOutput(_LLMBase):
    """Semantic clustering of the concept inventory."""

    root_label: str
    categories: list[LLMClusterCategory]


class LLMLabelTranslation(_LLMBase):
    source: str
    translated: str


class LLMLabelTranslations(_LLMBase):
    labels: list[LLMLabelTranslation]


# ---------------------------------------------------------------------------
# Internal pipeline models
# ---------------------------------------------------------------------------
class ConceptCard(BaseModel):
    """Deduplicated, grounded concept used to build leaf nodes."""

    id: str
    term: str
    explanation: str
    evidence: str = ""
    source_pages: list[int] = Field(default_factory=list)
    source_section: str = ""
    section_kind: SectionKind = "content"


class ClusterGroup(BaseModel):
    label: str
    concept_ids: list[str]


class ClusterCategory(BaseModel):
    label: str
    groups: list[ClusterGroup]


class ClusterPlan(BaseModel):
    root_label: str
    categories: list[ClusterCategory]


class GenerationOptions(BaseModel):
    """User-controlled generation knobs still accepted by the API."""

    max_depth: int = 3
    max_branches: int = 7
    language: str | None = None


MindMapNode.model_rebuild()
