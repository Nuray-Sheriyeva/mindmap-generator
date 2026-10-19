"""LangGraph happy paths, map-reduce routing and conditional repair loops."""

from __future__ import annotations

import time
from typing import Any

import pytest
from conftest import FakeLLMClient, make_tree

from mindmap_generator.config import Settings
from mindmap_generator.errors import GenerationError, LLMError
from mindmap_generator.graph.builder import build_graph
from mindmap_generator.graph.validate import flatten_tree
from mindmap_generator.models import MindMapNode

SETTINGS = Settings(max_pages=50, single_call_char_limit=50000)
MAP_SETTINGS = Settings(
    max_pages=50,
    single_call_char_limit=100,
    chunk_chars=200,
    chunk_overlap_chars=40,
)


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
        or {"max_depth": 3, "max_branches": 6, "max_children": 6, "language": None},
        "started_at": time.time(),
    }


async def _run(pdf_bytes: bytes, llm: FakeLLMClient, settings: Settings, store=None):
    graph = build_graph(settings, llm, store)
    return await graph.ainvoke(_state(pdf_bytes))


@pytest.mark.asyncio
async def test_single_call_happy_path(sample_pdf_bytes: bytes) -> None:
    llm = FakeLLMClient()
    store = RecordingStore()
    output = await _run(sample_pdf_bytes, llm, SETTINGS, store)

    result = output["result"]
    assert result["document"]["filename"] == "sample.pdf"
    assert result["document"]["pages"] == 3
    assert result["document"]["language"] == "en"
    assert result["meta"]["generation_path"] == "single_call"
    assert result["meta"]["repair_attempts"] == 0
    assert result["meta"]["model"] == "fake-model-v1"
    assert [call["schema_name"] for call in llm.calls] == ["hierarchy"]
    assert store.stages[0][1] == "parse_pdf"
    assert store.stages[-1][1] == "finalize"

    tree = MindMapNode.model_validate(result["mindmap"])
    ids = [node.id for node in flatten_tree(tree)]
    assert ids[0] == "root"
    assert len(ids) == len(set(ids)) == result["meta"]["node_count"]
    assert result["meta"]["depth"] <= 3
    assert all(1 <= page <= 3 for node in flatten_tree(tree) for page in node.source_pages)


@pytest.mark.asyncio
async def test_long_document_uses_map_reduce(sample_pdf_bytes: bytes) -> None:
    llm = FakeLLMClient()
    store = RecordingStore()
    output = await _run(sample_pdf_bytes, llm, MAP_SETTINGS, store)

    schemas = [call["schema_name"] for call in llm.calls]
    assert schemas.count("chunk_summary") >= 2
    assert schemas[-1] == "hierarchy"
    assert output["result"]["meta"]["generation_path"] == "map_reduce"
    assert "summarize_chunks" in [stage for _, stage in store.stages]
    assert "CHUNK SUMMARIES" in llm.calls[-1]["user"]


@pytest.mark.asyncio
async def test_validation_repair_loop(sample_pdf_bytes: bytes) -> None:
    invalid = make_tree(branches=1, children=2, depth=2)
    llm = FakeLLMClient(hierarchy_responses=[invalid, make_tree()])
    output = await _run(sample_pdf_bytes, llm, SETTINGS)

    assert output["result"]["meta"]["repair_attempts"] == 1
    assert len(llm.calls) == 2
    repair_prompt = llm.calls[-1]["user"]
    assert "VALIDATION ERRORS" in repair_prompt
    assert "at least 2 main branches" in repair_prompt


@pytest.mark.asyncio
async def test_repair_retries_are_bounded(sample_pdf_bytes: bytes) -> None:
    invalid = make_tree(branches=1, children=2, depth=2)
    llm = FakeLLMClient(hierarchy_responses=[invalid, invalid, invalid])
    with pytest.raises(GenerationError) as excinfo:
        await _run(sample_pdf_bytes, llm, SETTINGS)
    assert "could not produce a valid mind map" in excinfo.value.message
    # Initial call + two repair attempts.
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_llm_failure_propagates(sample_pdf_bytes: bytes) -> None:
    llm = FakeLLMClient(fail=True)
    with pytest.raises(LLMError):
        await _run(sample_pdf_bytes, llm, SETTINGS)


@pytest.mark.asyncio
async def test_language_override_and_depth_clamp(sample_pdf_bytes: bytes) -> None:
    llm = FakeLLMClient()
    options = {"max_depth": 2, "max_branches": 4, "max_children": 2, "language": "ru"}
    graph = build_graph(SETTINGS, llm)
    output = await graph.ainvoke(_state(sample_pdf_bytes, options))

    assert output["result"]["meta"]["output_language"] == "ru"
    assert output["result"]["meta"]["depth"] <= 2
    assert "OUTPUT LANGUAGE: Russian" in llm.calls[0]["user"]
    assert "MAX DEPTH BELOW ROOT: 2" in llm.calls[0]["user"]
