"""LangGraph concept-first happy path, repair loops and prompt checks."""

from __future__ import annotations

import time
from typing import Any

import pytest
from conftest import (
    FakeLLMClient,
    make_cluster,
    make_concepts,
    make_invalid_cluster,
    make_russian_concepts,
)

from mindmap_generator.config import Settings
from mindmap_generator.errors import GenerationError, LLMError
from mindmap_generator.graph.builder import build_graph
from mindmap_generator.graph.validate import count_leaves, flatten_tree
from mindmap_generator.llm.openai_compat import OpenAICompatibleClient
from mindmap_generator.models import MindMapNode

SETTINGS = Settings(max_pages=50, max_repair_attempts=2)


class RecordingStore:
    def __init__(self) -> None:
        self.stages: list[tuple[str, str]] = []

    def update_stage(self, job_id: str, stage: str) -> None:
        self.stages.append((job_id, stage))


def _state(pdf_bytes: bytes, options: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "job_id": "job-test",
        "pdf_bytes": pdf_bytes,
        "filename": "sample.pdf",
        "options": options
        or {"max_depth": 3, "max_branches": 7, "language": None},
        "started_at": time.time(),
    }


async def _run(pdf_bytes: bytes, llm: FakeLLMClient, settings: Settings, store=None):
    graph = build_graph(settings, llm, store)
    return await graph.ainvoke(_state(pdf_bytes))


def _assert_valid_result(result: dict[str, Any]) -> MindMapNode:
    tree = MindMapNode.model_validate(result["mindmap"])
    assert tree.kind == "root"
    nodes = flatten_tree(tree)
    assert all(node.explanation is None for node in nodes if node.kind != "leaf")
    leaves = [node for node in nodes if node.kind == "leaf"]
    assert leaves
    assert all(node.explanation and node.explanation.strip() for node in leaves)
    assert all(node.source_pages for node in leaves)
    assert len([node.id for node in nodes]) == len({node.id for node in nodes})
    assert result["meta"]["schema_version"] == 2
    assert result["meta"]["leaf_count"] == count_leaves(tree)
    assert result["meta"]["node_count"] == len(nodes)
    return tree


@pytest.mark.asyncio
async def test_happy_path_builds_visible_leaf_explanations(sample_pdf_bytes: bytes) -> None:
    llm = FakeLLMClient()
    store = RecordingStore()
    output = await _run(sample_pdf_bytes, llm, SETTINGS, store)
    result = output["result"]
    tree = _assert_valid_result(result)

    assert tree.label == "Photosynthesis"
    assert len(tree.children) == 4
    assert result["meta"]["generation_path"] == "concept_clustering"
    assert result["meta"]["repair_attempts"] == 0
    assert result["meta"]["leaf_count"] == 10
    assert result["document"]["pages"] == 3
    assert result["meta"]["model"] == "fake-model-v2"
    assert "Photosynthesis" in tree.label

    schemas = [call["schema_name"] for call in llm.calls]
    assert schemas.count("concept_extraction") >= 1
    assert schemas[-1] == "cluster"
    assert "concept_repair" not in schemas

    stages = [stage for _, stage in store.stages]
    assert stages[0] == "parse_pdf"
    assert "classify_sections" in stages
    assert "chunk_document" in stages
    assert "extract_concepts" in stages
    assert "build_hierarchy" in stages
    assert stages[-1] == "finalize"

    concept_call = next(
        call for call in llm.calls if call["schema_name"] == "concept_extraction"
    )
    assert "COVERAGE GOALS" in concept_call["user"]
    assert "learning objective" in concept_call["system"].lower()
    cluster_prompt = next(
        call["user"] for call in llm.calls if call["schema_name"] == "cluster"
    )
    assert "CONCEPT INVENTORY" in cluster_prompt
    assert "Category types" in llm.calls[-1]["system"]


@pytest.mark.asyncio
async def test_max_depth_two_flattens_subgroups(sample_pdf_bytes: bytes) -> None:
    ids = [f"c{index}" for index in range(1, 11)]
    cluster = {
        "root_label": "Photosynthesis",
        "categories": [
            {"label": "Core Concepts", "groups": [{"label": "Details", "concept_ids": ids[0:3]}]},
            {"label": "Light Reactions", "groups": [{"label": "Details", "concept_ids": ids[3:6]}]},
            {"label": "Calvin Cycle", "groups": [{"label": "Details", "concept_ids": ids[6:8]}]},
            {"label": "Applications", "groups": [{"label": "Details", "concept_ids": ids[8:10]}]},
        ],
    }
    llm = FakeLLMClient(cluster_responses=[cluster])
    graph = build_graph(SETTINGS, llm)
    output = await graph.ainvoke(
        _state(sample_pdf_bytes, {"max_depth": 2, "max_branches": 7, "language": None})
    )
    tree = _assert_valid_result(output["result"])
    assert len(tree.children) == 4
    assert all(
        child.kind == "leaf" for branch in tree.children for child in branch.children
    )


@pytest.mark.asyncio
async def test_concept_repair_loop(sample_pdf_bytes: bytes) -> None:
    bad = make_concepts()
    bad["concepts"][0]["explanation"] = "Explain what photosynthesis is in plain language."
    llm = FakeLLMClient(concept_responses=[bad for _ in range(8)])
    output = await _run(sample_pdf_bytes, llm, SETTINGS)

    result = output["result"]
    _assert_valid_result(result)
    assert result["meta"]["repair_attempts"] == 1
    schemas = [call["schema_name"] for call in llm.calls]
    assert "concept_repair" in schemas
    repair_prompt = next(
        call["user"] for call in llm.calls if call["schema_name"] == "concept_repair"
    )
    assert "INVALID CONCEPTS" in repair_prompt
    assert "task/learning objective" in repair_prompt


@pytest.mark.asyncio
async def test_cluster_repair_loop(sample_pdf_bytes: bytes) -> None:
    ids = [f"c{index}" for index in range(1, 11)]
    llm = FakeLLMClient(cluster_responses=[make_invalid_cluster(ids)])
    output = await _run(sample_pdf_bytes, llm, SETTINGS)

    result = output["result"]
    _assert_valid_result(result)
    assert result["meta"]["repair_attempts"] == 1
    schemas = [call["schema_name"] for call in llm.calls]
    assert "cluster_repair" in schemas
    repair_prompt = next(
        call["user"] for call in llm.calls if call["schema_name"] == "cluster_repair"
    )
    assert "VALIDATION ERRORS" in repair_prompt
    assert "scaffolding" in repair_prompt.lower() or "Learning Objectives" in repair_prompt


@pytest.mark.asyncio
async def test_repair_attempts_are_bounded(sample_pdf_bytes: bytes) -> None:
    ids = [f"c{index}" for index in range(1, 11)]
    invalid = make_invalid_cluster(ids)
    llm = FakeLLMClient(
        cluster_responses=[invalid],
        cluster_repair_responses=[invalid, invalid],
    )
    with pytest.raises(GenerationError) as excinfo:
        await _run(sample_pdf_bytes, llm, SETTINGS)
    assert "could not produce a valid concept map" in excinfo.value.message
    schemas = [call["schema_name"] for call in llm.calls]
    assert schemas.count("cluster_repair") == 2


@pytest.mark.asyncio
async def test_llm_failure_propagates(sample_pdf_bytes: bytes) -> None:
    with pytest.raises(LLMError):
        await _run(sample_pdf_bytes, FakeLLMClient(fail=True), SETTINGS)


@pytest.mark.asyncio
async def test_language_override_translates_terms_and_explanations(
    sample_pdf_bytes: bytes,
) -> None:
    ids = [f"c{index}" for index in range(1, 11)]
    llm = FakeLLMClient(
        concept_responses=[make_russian_concepts() for _ in range(8)],
        cluster_responses=[make_cluster(ids)],
    )
    graph = build_graph(SETTINGS, llm)
    output = await graph.ainvoke(
        _state(
            sample_pdf_bytes,
            {"max_depth": 3, "max_branches": 7, "language": "ru"},
        )
    )
    result = output["result"]
    assert result["meta"]["output_language"] == "ru"
    assert result["meta"]["repair_attempts"] == 1
    tree = _assert_valid_result(result)
    leaves = [node for node in flatten_tree(tree) if node.kind == "leaf"]
    assert all(any("\u0400" <= char <= "\u04ff" for char in leaf.label) for leaf in leaves)
    assert all(
        any("\u0400" <= char <= "\u04ff" for char in (leaf.explanation or ""))
        for leaf in leaves
    )
    assert all(any("\u0400" <= char <= "\u04ff" for char in branch.label) for branch in tree.children)
    concept_call = next(
        call for call in llm.calls if call["schema_name"] == "concept_extraction"
    )
    assert "OUTPUT LANGUAGE: Russian" in concept_call["user"]
    assert "SOURCE LANGUAGE: English" in concept_call["user"]
    assert "copy evidence verbatim in English" in concept_call["user"]
    assert any(call["schema_name"] == "label_translation" for call in llm.calls)


@pytest.mark.asyncio
async def test_english_explanations_fail_russian_output_check(
    sample_pdf_bytes: bytes,
) -> None:
    llm = FakeLLMClient()
    graph = build_graph(SETTINGS, llm)
    with pytest.raises(GenerationError) as excinfo:
        await graph.ainvoke(
            _state(
                sample_pdf_bytes,
                {"max_depth": 3, "max_branches": 7, "language": "ru"},
            )
        )
    assert "requested output language" in excinfo.value.message


@pytest.mark.asyncio
async def test_learning_objectives_never_become_branches(objectives_pdf_bytes: bytes) -> None:
    cells = {
        "concepts": [
            {
                "term": "Cell membrane",
                "explanation": "The cell membrane controls what enters and leaves the cell.",
                "evidence": "A cell membrane controls what enters and leaves the cell.",
                "source_pages": [2],
            },
            {
                "term": "Nucleus",
                "explanation": "The nucleus stores genetic information inside the cell.",
                "evidence": "The nucleus stores genetic information.",
                "source_pages": [2],
            },
            {
                "term": "Cell wall",
                "explanation": "Plant cells have a cell wall that supports their shape.",
                "evidence": "Plant cells have a cell wall and chloroplasts.",
                "source_pages": [2],
            },
            {
                "term": "Chloroplasts",
                "explanation": "Plant cells contain chloroplasts used for photosynthesis.",
                "evidence": "Plant cells have a cell wall and chloroplasts.",
                "source_pages": [2],
            },
        ]
    }
    cluster = {
        "root_label": "Cells",
        "categories": [
            {
                "label": "Core Concepts",
                "groups": [{"label": "", "concept_ids": ["c1", "c2"]}],
            },
            {
                "label": "Plant Cells",
                "groups": [{"label": "", "concept_ids": ["c3", "c4"]}],
            },
        ],
    }
    llm = FakeLLMClient(
        concept_responses=[cells],
        cluster_responses=[cluster],
    )
    output = await _run(objectives_pdf_bytes, llm, SETTINGS)
    result = output["result"]
    tree = _assert_valid_result(result)
    labels = [node.label for node in flatten_tree(tree)]
    assert "Learning Objectives" not in labels
    assert tree.label == "Cells"
    assert result["meta"]["leaf_count"] == 4


@pytest.mark.asyncio
async def test_markdown_export_keeps_leaf_explanations(sample_pdf_bytes: bytes) -> None:
    from mindmap_generator.jobs.exports import export_markdown

    output = await _run(sample_pdf_bytes, FakeLLMClient(), SETTINGS)
    markdown = export_markdown(output["result"])
    assert "# Photosynthesis" in markdown
    assert "## Core Concepts" in markdown
    assert "Photosynthesis converts light energy into chemical energy." in markdown
    assert "_Source pages:" in markdown
    assert "summary" not in markdown.lower()


@pytest.mark.asyncio
async def test_missing_api_key_surfaces_specific_error(sample_pdf_bytes: bytes) -> None:
    settings = Settings(max_pages=50, llm_provider="openai", llm_api_key=None)
    client = OpenAICompatibleClient(settings)
    with pytest.raises(LLMError) as excinfo:
        await _run(sample_pdf_bytes, client, settings)
    assert "No LLM API key configured" in excinfo.value.message
