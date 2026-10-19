"""LangGraph nodes: parse → chunk → map → reduce → validate/repair → finalize."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..chunking import DocumentChunk, chunk_document
from ..config import Settings
from ..errors import GenerationError, LLMError
from ..languages import language_name, resolve_output_language
from ..llm.base import LLMClient
from ..models import (
    ChunkSummary,
    DocumentInfo,
    GenerationOptions,
    LLMChunkSummary,
    LLMLevel0Node,
    MindMapMeta,
    MindMapNode,
    MindMapResult,
)
from ..pdf.extract import parse_pdf_document
from ..pdf.types import DocumentSection
from ..prompts import build_hierarchy_prompt, build_repair_prompt, build_summarize_prompt
from .state import PipelineState
from .validate import (
    assign_stable_ids,
    count_nodes,
    tree_depth,
    validate_hierarchy,
)

logger = logging.getLogger(__name__)


class ProgressSink(Protocol):
    """Minimal interface the graph needs from the job store."""

    def update_stage(self, job_id: str, stage: str) -> None: ...


@dataclass(slots=True)
class GraphDependencies:
    """Dependencies injected into the compiled graph."""

    settings: Settings
    llm: LLMClient
    job_store: ProgressSink | None = None


def _report(deps: GraphDependencies, state: PipelineState, stage: str) -> None:
    job_id = state.get("job_id")
    if job_id and deps.job_store is not None:
        try:
            deps.job_store.update_stage(job_id, stage)
        except Exception:  # pragma: no cover - progress must never break generation
            logger.debug("Could not update job stage", exc_info=True)


def _options(state: PipelineState, settings: Settings) -> GenerationOptions:
    raw = state.get("options") or {}
    return GenerationOptions(
        max_depth=int(raw.get("max_depth", settings.default_max_depth)),
        max_branches=int(raw.get("max_branches", settings.default_max_branches)),
        max_children=int(raw.get("max_children", settings.max_children)),
        language=raw.get("language"),
    )


# ---------------------------------------------------------------------------
# Stage 1: parse
# ---------------------------------------------------------------------------
def make_parse_node(deps: GraphDependencies):
    async def parse_pdf(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "parse_pdf")
        document = await asyncio.to_thread(
            parse_pdf_document,
            state["pdf_bytes"],
            state["filename"],
            deps.settings,
        )
        return {
            "document": document.model_dump(),
            "sections": [section.model_dump() for section in document.sections],
            "warnings": list(document.warnings),
        }

    return parse_pdf


# ---------------------------------------------------------------------------
# Stage 2: chunk
# ---------------------------------------------------------------------------
def make_chunk_node(deps: GraphDependencies):
    async def chunk_document_node(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "chunk_document")
        sections = [DocumentSection.model_validate(item) for item in state["sections"]]
        chunks = chunk_document(
            sections,
            max_chars=deps.settings.chunk_chars,
            overlap_chars=deps.settings.chunk_overlap_chars,
        )
        if not chunks:
            raise GenerationError("The document produced no usable text chunks.")
        logger.info(
            "Chunked document sections=%d chunks=%d tokens=%d",
            len(sections),
            len(chunks),
            sum(chunk.token_estimate for chunk in chunks),
        )
        return {"chunks": [chunk.model_dump() for chunk in chunks]}

    return chunk_document_node


# ---------------------------------------------------------------------------
# Stage 3: map (concurrent)
# ---------------------------------------------------------------------------
def _sanitize_pages(raw_pages: Any, fallback: list[int], page_count: int) -> list[int]:
    pages: list[int] = []
    if isinstance(raw_pages, list):
        for value in raw_pages:
            try:
                page = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= page <= page_count:
                pages.append(page)
    return sorted(set(pages)) or list(fallback)


def make_summarize_node(deps: GraphDependencies):
    async def summarize_chunks(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "summarize_chunks")
        document = state["document"]
        page_count = int(document["pages"])
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        semaphore = asyncio.Semaphore(deps.settings.llm_concurrency)
        chunks = [DocumentChunk.model_validate(item) for item in state["chunks"]]
        barriers = state.get("warnings", [])

        async def summarize_one(chunk: DocumentChunk) -> ChunkSummary:
            system_prompt, user_prompt = build_summarize_prompt(
                chunk_text=chunk.text,
                section_title=chunk.section_title,
                page_numbers=chunk.source_pages,
                document_title=document["title"],
                language_name=language_name(output_language),
            )
            async with semaphore:
                raw = await deps.llm.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=LLMChunkSummary.model_json_schema(),
                    schema_name="chunk_summary",
                )
            parsed = LLMChunkSummary.model_validate(raw)
            concepts = [
                concept.model_copy(
                    update={
                        "source_pages": _sanitize_pages(
                            concept.source_pages, chunk.source_pages, page_count
                        )
                    }
                )
                for concept in parsed.key_concepts
                if concept.label.strip()
            ]
            return ChunkSummary(
                chunk_id=chunk.id,
                section_title=chunk.section_title,
                section_level=chunk.section_level,
                summary=parsed.summary.strip(),
                key_concepts=concepts,
                key_terms=[term.strip() for term in parsed.key_terms if term.strip()],
                source_pages=chunk.source_pages,
            )

        results = await asyncio.gather(
            *(summarize_one(chunk) for chunk in chunks), return_exceptions=True
        )
        summaries: list[ChunkSummary] = []
        failures = 0
        for chunk, result in zip(chunks, results, strict=True):
            if isinstance(result, BaseException):
                failures += 1
                logger.warning(
                    "Chunk summarization failed chunk=%s error=%s", chunk.id, result
                )
                continue
            summaries.append(result)

        if not summaries:
            raise LLMError("Every chunk failed to summarize; the LLM provider may be unavailable.")
        if failures:
            barriers.append(f"{failures} of {len(chunks)} chunks failed to summarize.")
        logger.info("Summarized chunks success=%d failed=%d", len(summaries), failures)
        return {
            "chunk_summaries": [summary.model_dump() for summary in summaries],
            "warnings": barriers,
        }

    return summarize_chunks


# ---------------------------------------------------------------------------
# Stage 4: reduce / single call
# ---------------------------------------------------------------------------
def _document_text(sections: list[DocumentSection], max_chars: int) -> tuple[str, bool]:
    parts = [f"## {section.title}\n{section.text}" for section in sections if section.text.strip()]
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _unwrap_root(raw: dict[str, Any]) -> dict[str, Any]:
    """Tolerate models that wrap the root in a ``{"root": ...}`` envelope."""
    if "label" not in raw and isinstance(raw.get("root"), dict):
        return raw["root"]
    return raw


def make_build_node(deps: GraphDependencies):
    async def build_hierarchy(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "build_hierarchy")
        document = state["document"]
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        sections = [DocumentSection.model_validate(item) for item in state["sections"]]
        warnings = state.get("warnings", [])

        summaries: list[ChunkSummary] | None = None
        document_text: str | None = None
        path = "map_reduce"
        if state.get("chunk_summaries"):
            summaries = [
                ChunkSummary.model_validate(item) for item in state["chunk_summaries"]
            ]
        else:
            path = "single_call"
            document_text, truncated = _document_text(sections, deps.settings.max_input_chars)
            if truncated:
                warnings.append(
                    "Document text was truncated to the configured input limit for the "
                    "single-call path."
                )

        min_branches = min(4, options.max_branches)
        system_prompt, user_prompt = build_hierarchy_prompt(
            document_title=document["title"],
            language_name=language_name(output_language),
            page_count=int(document["pages"]),
            max_depth=options.max_depth,
            min_branches=min_branches,
            max_branches=options.max_branches,
            sections=sections,
            chunk_summaries=summaries,
            document_text=document_text,
        )
        raw = await deps.llm.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=LLMLevel0Node.model_json_schema(),
            schema_name="hierarchy",
        )
        logger.info("Built hierarchy draft path=%s", path)
        return {
            "draft": _unwrap_root(raw),
            "generation_path": path,
            "warnings": warnings,
        }

    return build_hierarchy


# ---------------------------------------------------------------------------
# Stage 5: validate + conditional repair
# ---------------------------------------------------------------------------
def make_validate_node(deps: GraphDependencies):
    async def validate_and_repair(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "validate_and_repair")
        document = state["document"]
        options = _options(state, deps.settings)
        fixes = list(state.get("fixes", []))
        outcome = validate_hierarchy(
            state["draft"],
            options=options,
            page_count=int(document["pages"]),
            document_title=document["title"],
        )
        fixes.extend(outcome.fixes)

        if outcome.tree is not None and not outcome.errors:
            return {
                "mindmap": outcome.tree.model_dump(),
                "validation_errors": [],
                "fixes": fixes,
                "finalize_ready": True,
            }

        attempts = int(state.get("repair_attempts", 0))
        if attempts >= deps.settings.max_repair_attempts or outcome.tree is None:
            if attempts >= deps.settings.max_repair_attempts:
                raise GenerationError(
                    "The LLM could not produce a valid mind map after "
                    f"{attempts} repair attempt(s).",
                    details={"errors": outcome.errors},
                )
            raise GenerationError(
                "The LLM response could not be validated.",
                details={"errors": outcome.errors},
            )

        logger.info(
            "Mind map draft invalid attempts=%d errors=%s", attempts, outcome.errors
        )
        return {
            "validation_errors": outcome.errors,
            "fixes": fixes,
            "finalize_ready": False,
        }

    return validate_and_repair


def make_repair_node(deps: GraphDependencies):
    async def request_repair(state: PipelineState) -> dict[str, Any]:
        document = state["document"]
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        attempts = int(state.get("repair_attempts", 0)) + 1
        system_prompt, user_prompt = build_repair_prompt(
            draft_json=json.dumps(state["draft"], ensure_ascii=False),
            errors=state.get("validation_errors", []),
            document_title=document["title"],
            language_name=language_name(output_language),
            max_depth=options.max_depth,
            max_branches=options.max_branches,
            page_count=int(document["pages"]),
        )
        raw = await deps.llm.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=LLMLevel0Node.model_json_schema(),
            schema_name="hierarchy",
        )
        logger.info("Requested mind map repair attempt=%d", attempts)
        return {
            "draft": _unwrap_root(raw),
            "repair_attempts": attempts,
            "validation_errors": [],
        }

    return request_repair


# ---------------------------------------------------------------------------
# Stage 6: finalize
# ---------------------------------------------------------------------------
def make_finalize_node(deps: GraphDependencies):
    async def finalize(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "finalize")
        document = state["document"]
        options = _options(state, deps.settings)
        tree = assign_stable_ids(MindMapNode.model_validate(state["mindmap"]))
        node_count = count_nodes(tree)
        depth = tree_depth(tree)
        started_at = float(state.get("started_at") or time.time())
        output_language = resolve_output_language(document["language"], options.language)
        result = MindMapResult(
            document=DocumentInfo(
                filename=document["filename"],
                pages=int(document["pages"]),
                language=document["language"],
                title=document.get("title"),
            ),
            mindmap=tree,
            meta=MindMapMeta(
                model=deps.llm.model,
                generated_at=datetime.now(UTC),
                node_count=node_count,
                depth=depth,
                repair_attempts=int(state.get("repair_attempts", 0)),
                generation_path=state.get("generation_path", "unknown"),
                processing_ms=max(0, int((time.time() - started_at) * 1000)),
                fixes=list(state.get("fixes", [])),
                output_language=output_language,
            ),
        )
        logger.info(
            "Finalized mind map nodes=%d depth=%d repairs=%d",
            node_count,
            depth,
            int(state.get("repair_attempts", 0)),
        )
        return {"result": result.model_dump(mode="json")}

    return finalize


def build_nodes(deps: GraphDependencies) -> dict[str, Any]:
    """Construct all node callables with dependencies captured."""
    return {
        "parse_pdf": make_parse_node(deps),
        "chunk_document": make_chunk_node(deps),
        "summarize_chunks": make_summarize_node(deps),
        "build_hierarchy": make_build_node(deps),
        "validate_and_repair": make_validate_node(deps),
        "request_repair": make_repair_node(deps),
        "finalize": make_finalize_node(deps),
    }
