"""LangGraph nodes: parse → classify → chunk → concepts → cluster → validate."""

from __future__ import annotations

import asyncio
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
    ClusterPlan,
    ConceptCard,
    DocumentInfo,
    GenerationOptions,
    LLMClusterOutput,
    LLMConceptList,
    LLMLabelTranslations,
    LLMRepairedConceptList,
    MindMapMeta,
    MindMapNode,
    MindMapResult,
)
from ..pdf.classify import classify_sections, page_text_map
from ..pdf.extract import parse_pdf_document
from ..pdf.types import DocumentSection
from ..prompts import (
    build_cluster_prompt,
    build_cluster_repair_prompt,
    build_concept_prompt,
    build_concept_repair_prompt,
    build_label_translation_prompt,
)
from .concepts import merge_concepts
from .state import PipelineState
from .validate import (
    ValidationOutcome,
    assign_stable_ids,
    count_branches,
    count_leaves,
    count_nodes,
    page_excerpts,
    tree_depth,
    validate_map,
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
        language=raw.get("language"),
    )


def _warnings(state: PipelineState) -> list[str]:
    return list(state.get("warnings", []))


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
# Stage 2: classify sections
# ---------------------------------------------------------------------------
def make_classify_node(deps: GraphDependencies):
    async def classify_sections_node(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "classify_sections")
        sections = [DocumentSection.model_validate(item) for item in state["sections"]]
        classified, objectives = classify_sections(sections)
        pages = page_text_map(classified)
        excluded = [
            section for section in classified if section.kind not in {"content", "reference"}
        ]
        warnings = _warnings(state)
        if excluded:
            warnings.append(
                "Excluded non-content sections from the map: "
                + ", ".join(section.title for section in excluded[:8])
                + ("…" if len(excluded) > 8 else "")
            )
        logger.info(
            "Classified sections content=%d reference=%d excluded=%d objectives=%d",
            sum(1 for section in classified if section.kind == "content"),
            sum(1 for section in classified if section.kind == "reference"),
            len(excluded),
            len(objectives),
        )
        return {
            "sections": [section.model_dump() for section in classified],
            "objectives": objectives,
            "page_texts": pages,
            "warnings": warnings,
        }

    return classify_sections_node


# ---------------------------------------------------------------------------
# Stage 3: chunk content/reference sections
# ---------------------------------------------------------------------------
def make_chunk_node(deps: GraphDependencies):
    async def chunk_document_node(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "chunk_document")
        sections = [DocumentSection.model_validate(item) for item in state["sections"]]
        extractable = [
            section for section in sections if section.kind in {"content", "reference"}
        ]
        if not extractable:
            raise GenerationError("No content sections were found to build a mind map from.")
        chunks = chunk_document(
            extractable,
            max_chars=deps.settings.chunk_chars,
            overlap_chars=deps.settings.chunk_overlap_chars,
        )
        if not chunks:
            raise GenerationError("The document produced no usable content chunks.")
        logger.info(
            "Chunked %d content sections into %d chunks (%d estimated tokens)",
            len(extractable),
            len(chunks),
            sum(chunk.token_estimate for chunk in chunks),
        )
        return {"chunks": [chunk.model_dump() for chunk in chunks]}

    return chunk_document_node


# ---------------------------------------------------------------------------
# Stage 4: extract grounded concept cards (map, concurrent)
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


def make_extract_concepts_node(deps: GraphDependencies):
    async def extract_concepts(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "extract_concepts")
        configuration_error = deps.llm.configuration_error()
        if configuration_error:
            raise LLMError(configuration_error)
        document = state["document"]
        page_count = int(document["pages"])
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        semaphore = asyncio.Semaphore(deps.settings.llm_concurrency)
        chunks = [DocumentChunk.model_validate(item) for item in state["chunks"]]
        objectives = state.get("objectives", [])
        warnings = _warnings(state)

        async def extract_one(chunk: DocumentChunk) -> list[dict[str, Any]]:
            system_prompt, user_prompt = build_concept_prompt(
                chunk_text=chunk.text,
                section_title=chunk.section_title,
                section_kind=chunk.section_kind,
                page_numbers=chunk.source_pages,
                document_title=document["title"],
                language_name=language_name(output_language),
                source_language_name=language_name(document["language"]),
                objectives=objectives,
            )
            async with semaphore:
                raw = await deps.llm.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=LLMConceptList.model_json_schema(),
                    schema_name="concept_extraction",
                )
            parsed = LLMConceptList.model_validate(raw)
            cards: list[dict[str, Any]] = []
            for concept in parsed.concepts:
                cards.append(
                    {
                        "term": concept.term,
                        "explanation": concept.explanation,
                        "evidence": concept.evidence,
                        "source_pages": _sanitize_pages(
                            concept.source_pages, chunk.source_pages, page_count
                        ),
                        "source_section": chunk.section_title,
                        "section_kind": chunk.section_kind,
                    }
                )
            return cards

        results = await asyncio.gather(
            *(extract_one(chunk) for chunk in chunks), return_exceptions=True
        )
        raw_concepts: list[dict[str, Any]] = []
        failures: list[BaseException] = []
        for chunk, result in zip(chunks, results, strict=True):
            if isinstance(result, BaseException):
                failures.append(result)
                logger.warning("Concept extraction failed chunk=%s error=%s", chunk.id, result)
                continue
            raw_concepts.extend(result)

        first_failure = str(failures[0])[:400] if failures else "unknown error"
        if failures and isinstance(failures[0], LLMError):
            provider_body = str((failures[0].details or {}).get("body", ""))[:300]
            if provider_body:
                first_failure = f"{first_failure} Provider detail: {provider_body}"
        if not raw_concepts:
            if failures:
                raise LLMError(
                    f"Concept extraction failed for every chunk: {first_failure}",
                    details={"error": first_failure, "failed_chunks": len(failures)},
                )
            raise GenerationError(
                "No grounded concepts could be extracted from this document. It may contain "
                "only learning objectives, activities or metadata."
            )
        if failures:
            warnings.append(
                f"{len(failures)} of {len(chunks)} concept-extraction calls failed. "
                f"First error: {first_failure}"
            )
            if len(raw_concepts) < max(4, len(chunks)):
                raise LLMError(
                    "Too few concept-extraction calls succeeded to build a map: "
                    f"{first_failure}",
                    details={"error": first_failure},
                )

        merged = merge_concepts(
            raw_concepts,
            page_count=page_count,
            max_concepts=deps.settings.max_concepts,
        )
        if not merged.concepts:
            raise GenerationError("No usable concept cards were produced.")
        warnings.extend(merged.warnings)
        logger.info(
            "Extracted %d raw concept cards; %d unique concepts after merge",
            len(raw_concepts),
            len(merged.concepts),
        )
        return {
            "concepts": [concept.model_dump() for concept in merged.concepts],
            "warnings": warnings,
        }

    return extract_concepts


# ---------------------------------------------------------------------------
# Stage 5: cluster concepts (reduce)
# ---------------------------------------------------------------------------
def make_build_node(deps: GraphDependencies):
    async def build_hierarchy(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "build_hierarchy")
        document = state["document"]
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        concepts = [ConceptCard.model_validate(item) for item in state["concepts"]]
        max_branches = max(4, min(options.max_branches, deps.settings.max_branches_limit))
        system_prompt, user_prompt = build_cluster_prompt(
            document_title=document["title"],
            language_name=language_name(output_language),
            page_count=int(document["pages"]),
            concepts=concepts,
            objectives=state.get("objectives", []),
            max_branches=max_branches,
        )
        raw = await deps.llm.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=LLMClusterOutput.model_json_schema(),
            schema_name="cluster",
        )
        logger.info("Built semantic cluster draft for %d concepts", len(concepts))
        return {
            "cluster": raw,
            "generation_path": "concept_clustering",
        }

    return build_hierarchy


# ---------------------------------------------------------------------------
# Stage 6: validate + targeted repair
# ---------------------------------------------------------------------------
def _content_section_count(sections: list[dict[str, Any]]) -> int:
    return sum(1 for section in sections if section.get("kind") in {"content", "reference"})


def make_validate_node(deps: GraphDependencies):
    async def validate_and_repair(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "validate_and_repair")
        document = state["document"]
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        concepts = [ConceptCard.model_validate(item) for item in state["concepts"]]
        page_texts = {
            int(page): text for page, text in (state.get("page_texts") or {}).items()
        }
        content_sections = _content_section_count(state.get("sections", []))
        min_leaves = min(len(concepts), max(6, min(24, content_sections * 2)))
        fixes = list(state.get("fixes", []))
        outcome: ValidationOutcome = validate_map(
            concepts,
            state.get("cluster") or {},
            document_title=document["title"],
            page_texts=page_texts,
            settings=deps.settings,
            max_branches=max(4, min(options.max_branches, deps.settings.max_branches_limit)),
            min_leaves=min_leaves,
            max_depth=options.max_depth,
            output_language=output_language,
            document_language=document["language"],
        )
        fixes.extend(outcome.fixes)

        if outcome.valid and outcome.tree is not None:
            return {
                "mindmap": outcome.tree.model_dump(),
                "concepts": [concept.model_dump() for concept in outcome.concepts],
                "validation_errors": [],
                "repair_errors_by_id": {},
                "repair_target": "",
                "fixes": fixes,
                "finalize_ready": True,
            }

        attempts = int(state.get("repair_attempts", 0))
        if attempts >= deps.settings.max_repair_attempts:
            summary = " | ".join(outcome.errors[:4])[:900]
            raise GenerationError(
                "The LLM could not produce a valid concept map after "
                f"{attempts} repair attempt(s). Validation issues: {summary}",
                details={"errors": outcome.errors[:20]},
            )

        language_errors = [
            error
            for error in outcome.cluster_errors
            if "not in the requested output language" in error
        ]
        other_cluster_errors = [
            error for error in outcome.cluster_errors if error not in language_errors
        ]
        if outcome.concept_errors:
            target = "concepts"
        elif language_errors and not other_cluster_errors:
            target = "labels"
        else:
            target = "clusters"
        logger.info(
            "Mind map invalid target=%s attempts=%d errors=%s",
            target,
            attempts,
            outcome.errors[:6],
        )
        return {
            "concepts": [concept.model_dump() for concept in outcome.concepts],
            "validation_errors": outcome.errors,
            "repair_errors_by_id": outcome.concept_errors,
            "repair_target": target,
            "fixes": fixes,
            "finalize_ready": False,
        }

    return validate_and_repair


def make_repair_node(deps: GraphDependencies):
    async def request_repair(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "validate_and_repair")
        document = state["document"]
        options = _options(state, deps.settings)
        output_language = resolve_output_language(document["language"], options.language)
        attempts = int(state.get("repair_attempts", 0)) + 1
        target = state.get("repair_target")
        concepts = [ConceptCard.model_validate(item) for item in state["concepts"]]

        if target == "concepts":
            errors_by_id = state.get("repair_errors_by_id", {})
            invalid = [
                concept for concept in concepts if concept.id in errors_by_id
            ] or concepts
            page_texts = {
                int(page): text for page, text in (state.get("page_texts") or {}).items()
            }
            system_prompt, user_prompt = build_concept_repair_prompt(
                document_title=document["title"],
                language_name=language_name(output_language),
                source_language_name=language_name(document["language"]),
                invalid_concepts=invalid,
                errors_by_id=errors_by_id,
                page_excerpts=page_excerpts(invalid, page_texts),
            )
            raw = await deps.llm.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=LLMRepairedConceptList.model_json_schema(),
                schema_name="concept_repair",
            )
            repaired = LLMRepairedConceptList.model_validate(raw)
            by_id = {item.id: item for item in repaired.concepts}
            updated: list[ConceptCard] = []
            for concept in concepts:
                replacement = by_id.get(concept.id)
                if replacement is None:
                    updated.append(concept)
                    continue
                updated.append(
                    concept.model_copy(
                        update={
                            "term": replacement.term,
                            "explanation": replacement.explanation,
                            "evidence": replacement.evidence,
                            "source_pages": replacement.source_pages or concept.source_pages,
                        }
                    )
                )
            logger.info("Repaired %d concepts (attempt %d)", len(invalid), attempts)
            return {
                "concepts": [concept.model_dump() for concept in updated],
                "repair_attempts": attempts,
                "repair_target": "",
                "validation_errors": [],
            }

        if target == "labels":
            try:
                plan = ClusterPlan.model_validate(state.get("cluster") or {})
            except Exception as exc:
                raise GenerationError(
                    "The cluster structure is not valid enough to translate its labels."
                ) from exc
            labels: list[str] = []
            for category in plan.categories:
                labels.append(category.label)
                for group in category.groups:
                    if group.label:
                        labels.append(group.label)
            labels = list(dict.fromkeys(label for label in labels if label.strip()))
            system_prompt, user_prompt = build_label_translation_prompt(
                labels=labels,
                language_name=language_name(output_language),
            )
            raw = await deps.llm.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=LLMLabelTranslations.model_json_schema(),
                schema_name="label_translation",
            )
            translated = LLMLabelTranslations.model_validate(raw)
            mapping = {
                item.source.casefold().strip(): item.translated.strip()
                for item in translated.labels
                if item.source.strip() and item.translated.strip()
            }
            for category in plan.categories:
                category.label = mapping.get(category.label.casefold().strip(), category.label)
                for group in category.groups:
                    if group.label:
                        group.label = mapping.get(
                            group.label.casefold().strip(), group.label
                        )
            logger.info("Translated %d map labels (attempt %d)", len(labels), attempts)
            return {
                "cluster": plan.model_dump(),
                "repair_attempts": attempts,
                "repair_target": "",
                "validation_errors": [],
            }

        if target == "clusters":
            try:
                current = ClusterPlan.model_validate(state.get("cluster") or {})
            except Exception:
                current = ClusterPlan(root_label=document["title"], categories=[])
            max_branches = max(
                4, min(options.max_branches, deps.settings.max_branches_limit)
            )
            system_prompt, user_prompt = build_cluster_repair_prompt(
                document_title=document["title"],
                language_name=language_name(output_language),
                page_count=int(document["pages"]),
                concepts=concepts,
                cluster=current,
                errors=state.get("validation_errors", []),
                objectives=state.get("objectives", []),
                max_branches=max_branches,
            )
            raw = await deps.llm.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=LLMClusterOutput.model_json_schema(),
                schema_name="cluster_repair",
            )
            logger.info("Repaired cluster plan (attempt %d)", attempts)
            return {
                "cluster": raw,
                "repair_attempts": attempts,
                "repair_target": "",
                "validation_errors": [],
            }

        raise GenerationError("The pipeline requested an unknown repair target.")

    return request_repair


# ---------------------------------------------------------------------------
# Stage 7: finalize
# ---------------------------------------------------------------------------
def make_finalize_node(deps: GraphDependencies):
    async def finalize(state: PipelineState) -> dict[str, Any]:
        _report(deps, state, "finalize")
        document = state["document"]
        options = _options(state, deps.settings)
        tree = assign_stable_ids(MindMapNode.model_validate(state["mindmap"]))
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
                schema_version=2,
                model=deps.llm.model,
                generated_at=datetime.now(UTC),
                node_count=count_nodes(tree),
                leaf_count=count_leaves(tree),
                branch_count=count_branches(tree),
                depth=tree_depth(tree),
                repair_attempts=int(state.get("repair_attempts", 0)),
                generation_path=state.get("generation_path", "concept_clustering"),
                output_language=output_language,
                processing_ms=max(0, int((time.time() - started_at) * 1000)),
                fixes=list(state.get("fixes", [])),
                warnings=list(state.get("warnings", [])),
            ),
        )
        logger.info(
            "Finalized map nodes=%d leaves=%d branches=%d depth=%d repairs=%d",
            result.meta.node_count,
            result.meta.leaf_count,
            result.meta.branch_count,
            result.meta.depth,
            result.meta.repair_attempts,
        )
        return {"result": result.model_dump(mode="json")}

    return finalize


def build_nodes(deps: GraphDependencies) -> dict[str, Any]:
    """Construct all node callables with dependencies captured."""
    return {
        "parse_pdf": make_parse_node(deps),
        "classify_sections": make_classify_node(deps),
        "chunk_document": make_chunk_node(deps),
        "extract_concepts": make_extract_concepts_node(deps),
        "build_hierarchy": make_build_node(deps),
        "validate_and_repair": make_validate_node(deps),
        "request_repair": make_repair_node(deps),
        "finalize": make_finalize_node(deps),
    }
