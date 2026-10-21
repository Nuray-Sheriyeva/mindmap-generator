"""Shared test fixtures: programmatically generated PDFs and a scripted LLM."""

from __future__ import annotations

import copy
import json
import re
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


def build_objectives_pdf() -> bytes:
    """PDF whose first section is a learning-objectives section."""
    doc = pymupdf.open()
    page = _page(doc, 1)
    page.insert_text((72, 80), "Cells", fontsize=22, fontname="hebo")
    page.insert_text((72, 120), "1. Learning Objectives", fontsize=16, fontname="hebo")
    page.insert_text((72, 150), "Explain what a cell membrane is.", fontsize=11)
    page.insert_text((72, 168), "Describe the role of the nucleus.", fontsize=11)
    page.insert_text((72, 186), "Distinguish plant and animal cells.", fontsize=11)

    page = _page(doc, 2)
    page.insert_text((72, 80), "2. Cell Structure", fontsize=16, fontname="hebo")
    page.insert_text((72, 110), "A cell membrane controls what enters and leaves the cell.", fontsize=11)
    page.insert_text((72, 128), "The nucleus stores genetic information.", fontsize=11)
    page.insert_text((72, 146), "Plant cells have a cell wall and chloroplasts.", fontsize=11)
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


DEFAULT_CONCEPTS: list[dict[str, Any]] = [
    {
        "term": "Photosynthesis",
        "explanation": "Photosynthesis converts light energy into chemical energy.",
        "evidence": "Photosynthesis converts light energy into chemical energy.",
        "source_pages": [1],
    },
    {
        "term": "Chloroplasts",
        "explanation": "Photosynthesis occurs in chloroplasts and produces oxygen.",
        "evidence": "It occurs in chloroplasts and produces oxygen.",
        "source_pages": [1],
    },
    {
        "term": "Oxygen release",
        "explanation": "Water splitting releases oxygen as a by-product of light reactions.",
        "evidence": "They split water and release oxygen.",
        "source_pages": [2],
    },
    {
        "term": "Light reactions",
        "explanation": "Light reactions occur in the thylakoid membrane and generate ATP and NADPH.",
        "evidence": "Light reactions occur in the thylakoid membrane.",
        "source_pages": [2],
    },
    {
        "term": "Thylakoid membrane",
        "explanation": "The thylakoid membrane is where light reactions take place.",
        "evidence": "Light reactions occur in the thylakoid membrane.",
        "source_pages": [2],
    },
    {
        "term": "Calvin cycle",
        "explanation": "The Calvin cycle fixes carbon dioxide into glucose using ATP and NADPH.",
        "evidence": "The Calvin cycle fixes carbon dioxide into glucose.",
        "source_pages": [2],
    },
    {
        "term": "ATP and NADPH",
        "explanation": "ATP and NADPH carry energy from light reactions into the Calvin cycle.",
        "evidence": "It uses ATP and NADPH produced by the light reactions.",
        "source_pages": [2],
    },
    {
        "term": "Glucose",
        "explanation": "The Calvin cycle produces glucose from carbon dioxide.",
        "evidence": "The Calvin cycle fixes carbon dioxide into glucose.",
        "source_pages": [2],
    },
    {
        "term": "Agriculture",
        "explanation": "Photosynthesis research informs agriculture and crop production.",
        "evidence": "Photosynthesis research informs agriculture and renewable energy.",
        "source_pages": [3],
    },
    {
        "term": "Artificial photosynthesis",
        "explanation": "Artificial photosynthesis aims to produce fuels from light.",
        "evidence": "Artificial photosynthesis aims to produce fuels.",
        "source_pages": [3],
    },
]

CATEGORY_LABELS = ["Core Concepts", "Light Reactions", "Calvin Cycle", "Applications"]

RUSSIAN_CONCEPTS: list[dict[str, Any]] = [
    {
        "term": "Фотосинтез",
        "explanation": "Фотосинтез преобразует световую энергию в химическую.",
        "evidence": "Photosynthesis converts light energy into chemical energy.",
        "source_pages": [1],
    },
    {
        "term": "Хлоропласты",
        "explanation": "Фотосинтез происходит в хлоропластах и выделяет кислород.",
        "evidence": "It occurs in chloroplasts and produces oxygen.",
        "source_pages": [1],
    },
    {
        "term": "Выделение кислорода",
        "explanation": "Расщепление воды выделяет кислород как побочный продукт световых реакций.",
        "evidence": "They split water and release oxygen.",
        "source_pages": [2],
    },
    {
        "term": "Световые реакции",
        "explanation": "Световые реакции происходят в тилакоидной мембране и создают АТФ и НАДФН.",
        "evidence": "Light reactions occur in the thylakoid membrane.",
        "source_pages": [2],
    },
    {
        "term": "Тилакоидная мембрана",
        "explanation": "В тилакоидной мембране протекают световые реакции.",
        "evidence": "Light reactions occur in the thylakoid membrane.",
        "source_pages": [2],
    },
    {
        "term": "Цикл Кальвина",
        "explanation": "Цикл Кальвина фиксирует углекислый газ в глюкозу с использованием АТФ и НАДФН.",
        "evidence": "The Calvin cycle fixes carbon dioxide into glucose.",
        "source_pages": [2],
    },
    {
        "term": "АТФ и НАДФН",
        "explanation": "АТФ и НАДФН переносят энергию из световых реакций в цикл Кальвина.",
        "evidence": "It uses ATP and NADPH produced by the light reactions.",
        "source_pages": [2],
    },
    {
        "term": "Глюкоза",
        "explanation": "Цикл Кальвина производит глюкозу из углекислого газа.",
        "evidence": "The Calvin cycle fixes carbon dioxide into glucose.",
        "source_pages": [2],
    },
    {
        "term": "Сельское хозяйство",
        "explanation": "Исследования фотосинтеза помогают сельскому хозяйству и производству культур.",
        "evidence": "Photosynthesis research informs agriculture and renewable energy.",
        "source_pages": [3],
    },
    {
        "term": "Искусственный фотосинтез",
        "explanation": "Искусственный фотосинтез направлен на получение топлива из света.",
        "evidence": "Artificial photosynthesis aims to produce fuels.",
        "source_pages": [3],
    },
]


def make_concepts(count: int = 10) -> dict[str, Any]:
    return {"concepts": copy.deepcopy(DEFAULT_CONCEPTS[:count])}


def make_russian_concepts(count: int = 10) -> dict[str, Any]:
    return {"concepts": copy.deepcopy(RUSSIAN_CONCEPTS[:count])}


def make_russian_cluster(concept_ids: list[str]) -> dict[str, Any]:
    labels = ["Основные понятия", "Световые реакции", "Цикл Кальвина", "Применение"]
    categories: list[dict[str, Any]] = []
    count = min(4, max(1, len(concept_ids) // 2))
    base, extra = divmod(len(concept_ids), count)
    index = 0
    for position in range(count):
        take = base + (1 if position < extra else 0)
        ids = concept_ids[index : index + take]
        index += take
        if not ids:
            continue
        categories.append(
            {
                "label": labels[position % len(labels)],
                "groups": [{"label": "", "concept_ids": ids}],
            }
        )
    return {"root_label": "Фотосинтез", "categories": categories}


def make_cluster(concept_ids: list[str]) -> dict[str, Any]:
    """Build a valid four-category cluster from IDs."""
    if not concept_ids:
        return {"root_label": "Photosynthesis", "categories": []}
    categories: list[dict[str, Any]] = []
    count = min(4, max(1, len(concept_ids) // 2))
    base, extra = divmod(len(concept_ids), count)
    index = 0
    for position in range(count):
        take = base + (1 if position < extra else 0)
        ids = concept_ids[index : index + take]
        index += take
        if not ids:
            continue
        categories.append(
            {
                "label": CATEGORY_LABELS[position % len(CATEGORY_LABELS)],
                "groups": [{"label": "", "concept_ids": ids}],
            }
        )
    return {"root_label": "Photosynthesis", "categories": categories}


def make_invalid_cluster(concept_ids: list[str]) -> dict[str, Any]:
    """One category named like a document scaffold section (invalid)."""
    return {
        "root_label": "Photosynthesis",
        "categories": [
            {
                "label": "Learning Objectives",
                "groups": [{"label": "", "concept_ids": concept_ids}],
            }
        ],
    }


def _inventory_ids(prompt: str) -> list[str]:
    return re.findall(r"^- (c\d+) \|", prompt, re.MULTILINE)


RU_LABEL_TRANSLATIONS = {
    "Core Concepts": "Основные понятия",
    "Light Reactions": "Световые реакции",
    "Calvin Cycle": "Цикл Кальвина",
    "Applications": "Применение",
    "Overview": "Обзор",
    "Details": "Детали",
    "Examples": "Примеры",
    "Additional": "Дополнительно",
    "Further": "Далее",
    "Context": "Контекст",
}


def _labels_from_translation_prompt(prompt: str) -> list[str]:
    match = re.search(r"LABELS TO TRANSLATE:\s*\n(.*)", prompt, re.DOTALL)
    if not match:
        return []
    labels: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            labels.append(stripped[2:].strip())
    return labels


def _concept_ids_from_repair(prompt: str) -> list[dict[str, Any]]:
    match = re.search(r"INVALID CONCEPTS:\s*<<<\s*(.*?)\s*>>>", prompt, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return []


class FakeLLMClient(LLMClient):
    """Scripted LLM: no network, deterministic responses, call recording."""

    provider = "fake"
    model = "fake-model-v2"

    def __init__(
        self,
        *,
        concept_responses: list[dict[str, Any] | Exception] | None = None,
        cluster_responses: list[dict[str, Any] | Exception] | None = None,
        concept_repair_responses: list[dict[str, Any] | Exception] | None = None,
        cluster_repair_responses: list[dict[str, Any] | Exception] | None = None,
        label_translation_responses: list[dict[str, Any] | Exception] | None = None,
        fail: bool = False,
    ) -> None:
        self.concept_responses = list(concept_responses or [])
        self.cluster_responses = list(cluster_responses or [])
        self.concept_repair_responses = list(concept_repair_responses or [])
        self.cluster_repair_responses = list(cluster_repair_responses or [])
        self.label_translation_responses = list(label_translation_responses or [])
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

        if schema_name == "concept_extraction":
            if self.concept_responses:
                response = self.concept_responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return copy.deepcopy(response)
            return make_concepts()

        if schema_name == "cluster":
            if self.cluster_responses:
                response = self.cluster_responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return copy.deepcopy(response)
            return make_cluster(_inventory_ids(user_prompt))

        if schema_name == "concept_repair":
            if self.concept_repair_responses:
                response = self.concept_repair_responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return copy.deepcopy(response)
            repaired = []
            for card in _concept_ids_from_repair(user_prompt):
                repaired.append(
                    {
                        "id": card.get("id", ""),
                        "term": card.get("term", "Concept"),
                        "explanation": card.get("evidence")
                        or f"{card.get('term', 'The concept')} is explained in the source text.",
                        "evidence": card.get("evidence", ""),
                        "source_pages": card.get("source_pages") or [1],
                    }
                )
            return {"concepts": repaired}

        if schema_name == "cluster_repair":
            if self.cluster_repair_responses:
                response = self.cluster_repair_responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return copy.deepcopy(response)
            return make_cluster(_inventory_ids(user_prompt))

        if schema_name == "label_translation":
            if self.label_translation_responses:
                response = self.label_translation_responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return copy.deepcopy(response)
            return {
                "labels": [
                    {
                        "source": label,
                        "translated": RU_LABEL_TRANSLATIONS.get(label, label),
                    }
                    for label in _labels_from_translation_prompt(user_prompt)
                ]
            }

        return {}


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    return build_sample_pdf()


@pytest.fixture(scope="session")
def objectives_pdf_bytes() -> bytes:
    return build_objectives_pdf()


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
