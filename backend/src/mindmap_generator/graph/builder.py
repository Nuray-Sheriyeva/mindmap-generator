"""Compile the LangGraph pipeline once per application."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..llm.base import LLMClient
from .nodes import GraphDependencies, ProgressSink, build_nodes
from .state import PipelineState


def build_graph(
    settings: Settings,
    llm: LLMClient,
    job_store: ProgressSink | None = None,
) -> Any:
    """Build and compile the mind map StateGraph.

    Graph shape::

        START → parse_pdf → chunk_document
                 ├─ long document → summarize_chunks → build_hierarchy
                 └─ short document → build_hierarchy
              → validate_and_repair ─┬─ valid → finalize → END
                                     └─ invalid → request_repair → validate_and_repair
    """
    deps = GraphDependencies(settings=settings, llm=llm, job_store=job_store)
    nodes = build_nodes(deps)

    graph: StateGraph = StateGraph(PipelineState)
    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.add_edge(START, "parse_pdf")
    graph.add_edge("parse_pdf", "chunk_document")

    def route_after_chunking(state: PipelineState) -> str:
        total_chars = sum(len(chunk.get("text", "")) for chunk in state.get("chunks", []))
        if total_chars <= settings.single_call_char_limit:
            return "build_hierarchy"
        return "summarize_chunks"

    graph.add_conditional_edges(
        "chunk_document",
        route_after_chunking,
        {
            "build_hierarchy": "build_hierarchy",
            "summarize_chunks": "summarize_chunks",
        },
    )
    graph.add_edge("summarize_chunks", "build_hierarchy")
    graph.add_edge("build_hierarchy", "validate_and_repair")

    def route_after_validation(state: PipelineState) -> str:
        return "finalize" if state.get("finalize_ready") else "request_repair"

    graph.add_conditional_edges(
        "validate_and_repair",
        route_after_validation,
        {
            "finalize": "finalize",
            "request_repair": "request_repair",
        },
    )
    graph.add_edge("request_repair", "validate_and_repair")
    graph.add_edge("finalize", END)

    return graph.compile()
