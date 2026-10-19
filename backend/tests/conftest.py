"""Shared test fixtures: programmatically generated PDFs and a scripted LLM."""

from __future__ import annotations

import copy
from typing import Any

import pymupdf
import pytest

from mindmap_generator.errors import LLMError
from mindmap_generator.llm.base import LLMClient


def _page(doc: pymupdf.Document, number: int) -> pymupdf.Page:
    page = doc.new_page()
    page.insert_text((72, 36), "Sample Document", fontsize=9, fontname="helv")
    page.insert_text((72, 806), f"Page {number}", fontsize=9, fontname="helv")
    return page


def build_sample_pdf() -> bytes:
    """Three-page text PDF with headings, running header/footer and hyphenation."""
    doc = pymupdf.open()

    page = _page(doc, 1)
    page.insert_text((72, 80), "Photosynthesis", fontsize=24, fontname="hebo")
    page.insert_text((72, 120), "1. Introduction", fontsize=16, fontname="hebo")
    page.insert_text((72, 155), "Photosynthesis converts light energy into chemical energy.", fontsize=11)
    page.insert_text((72, 173), "It occurs in chloroplasts and produces oxygen. Photo-", fontsize=11)
    page.insert_text((72, 191), "synthesis is essential for life on Earth.", fontsize=11)
    page.insert_text((72, 225), "Plants, algae and some bacteria perform this process.", fontsize=11)

    page = _page(doc, 2)
    page.insert_text((72, 80), "1.1 Light Reactions", fontsize=14, fontname="hebo")
    page.insert_text((72, 110), "Light reactions occur in the thylakoid membrane.", fontsize=11)
    page.insert_text((72, 128), "They split water and release oxygen.", fontsize=11)
    page.insert_text((72, 190), "1.2 Calvin Cycle", fontsize=14, fontname="hebo")
    page.insert_text((72, 220), "The Calvin cycle fixes carbon dioxide into glucose.", fontsize=11)
    page.insert_text((72, 238), "It uses ATP and NADPH produced by the light reactions.", fontsize=11)

    page = _page(doc, 3)
    page.insert_text((72, 80), "2. Applications", fontsize=16, fontname="hebo")
    page.insert_text((72, 110), "Photosynthesis research informs agriculture and renewable energy.", fontsize=11)
    page.insert_text((72, 128), "Artificial photosynthesis aims to produce fuels.", fontsize=11)

    return doc.tobytes()


def build_outline_pdf() -> bytes:
    """PDF with bookmarks so outline detection takes priority."""
    doc = pymupdf.open()
    entries = [
        ("Overview", "An overview of the study and its goals."),
        ("Background", "Background information about the topic."),
        ("Methods", "Methods used to collect and analyze data."),
        ("Results", "Results show a clear improvement over baseline."),
    ]
    for index, (title, body) in enumerate(entries, start=1):
        page = _page(doc, index)
        page.insert_text((72, 90), title, fontsize=18, fontname="hebo")
        page.insert_textbox(
            pymupdf.Rect(72, 115, 540, 260),
            body,
            fontsize=11,
            fontname="helv",
        )
    doc.set_toc([[1, "Overview", 1], [1, "Background", 2], [1, "Methods", 3], [1, "Results", 4]])
    return doc.tobytes()


def build_blank_pdf() -> bytes:
    """Single page without any text layer (simulates a scanned page)."""
    doc = pymupdf.open()
    doc.new_page()
    return doc.tobytes()


def build_encrypted_pdf() -> bytes:
    """Single-page encrypted PDF."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Top secret text", fontsize=12)
    return doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )


def make_tree(*, branches: int = 4, children: int = 2, depth: int = 3) -> dict[str, Any]:
    """Build a schema-valid hierarchy for fake LLM responses."""

    def leaf(label: str, page: int) -> dict[str, Any]:
        return {
            "label": label,
            "summary": f"Evidence for {label} appears on page {page}.",
            "source_pages": [page],
            "children": [],
        }

    root_children = []
    for index in range(branches):
        page = (index % 3) + 1
        branch_children = []
        for child_index in range(children):
            child_label = f"Topic {index + 1}.{child_index + 1}"
            sub_children = []
            if depth >= 3 and child_index == 0:
                sub_children = [leaf(f"Detail {index + 1}.{child_index + 1}", page)]
            branch_children.append(
                {
                    "label": child_label,
                    "summary": f"Sub-topic about element {index + 1}.",
                    "source_pages": [page],
                    "children": sub_children,
                }
            )
        root_children.append(
            {
                "label": f"Branch {index + 1}",
                "summary": f"Main theme {index + 1} from the document.",
                "source_pages": [page],
                "children": branch_children,
            }
        )
    return {
        "label": "Photosynthesis",
        "summary": "The document explains photosynthesis and its applications.",
        "source_pages": [1],
        "children": root_children,
    }


CHUNK_RESPONSE: dict[str, Any] = {
    "summary": "This chunk introduces photosynthesis and light reactions.",
    "key_concepts": [
        {"label": "Light energy", "summary": "Light energy is converted into chemical energy.", "source_pages": [1]},
        {"label": "Oxygen release", "summary": "Water is split and oxygen is released.", "source_pages": [2]},
        {"label": "Calvin cycle", "summary": "Carbon dioxide is fixed into glucose.", "source_pages": [2]},
    ],
    "key_terms": ["photosynthesis", "chloroplasts", "glucose", "oxygen"],
}


class FakeLLMClient(LLMClient):
    """Scripted LLM: no network, deterministic responses, call recording."""

    provider = "fake"
    model = "fake-model-v1"

    def __init__(
        self,
        *,
        hierarchy_responses: list[dict[str, Any] | Exception] | None = None,
        chunk_response: dict[str, Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.hierarchy_responses = list(hierarchy_responses or [])
        self.chunk_response = copy.deepcopy(chunk_response or CHUNK_RESPONSE)
        self.fail = fail
        self.calls: list[dict[str, str]] = []

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str = "response",
    ) -> dict[str, Any]:
        self.calls.append(
            {"schema_name": schema_name, "system": system_prompt, "user": user_prompt}
        )
        if self.fail:
            raise LLMError("Simulated provider outage.")
        if schema_name == "chunk_summary":
            return copy.deepcopy(self.chunk_response)
        if self.hierarchy_responses:
            response = self.hierarchy_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return copy.deepcopy(response)
        return make_tree()


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    return build_sample_pdf()


@pytest.fixture(scope="session")
def outline_pdf_bytes() -> bytes:
    return build_outline_pdf()


@pytest.fixture(scope="session")
def blank_pdf_bytes() -> bytes:
    return build_blank_pdf()


@pytest.fixture(scope="session")
def encrypted_pdf_bytes() -> bytes:
    return build_encrypted_pdf()


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()
