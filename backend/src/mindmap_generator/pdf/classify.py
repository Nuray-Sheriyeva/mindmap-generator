"""Classify document sections into content, objectives, reference and scaffold.

The classifier keeps learning objectives/activities/glossary out of the map
hierarchy. Objectives are returned separately as a coverage checklist, while
glossary sections are marked as reference evidence for concept extraction.
"""

from __future__ import annotations

import re

from ..models import SectionKind
from .clean import normalize_text
from .types import DocumentSection

_OBJECTIVE_TITLES = re.compile(
    r"^(?:\d+[.)]\s*)?(?:learning\s+objectives?|lesson\s+objectives?|objectives?|"
    r"learning\s+outcomes?|goals?|what\s+you\s+will\s+learn|"
    r"цели\s+обучения|задачи\s+урока|цели\s+урока|"
    r"оқу\s+мақсаттары|сабақ\s+мақсаттары|мақсаттар)\b",
    re.IGNORECASE,
)
_ACTIVITY_TITLES = re.compile(
    r"^(?:\d+[.)]\s*)?(?:activities|activity|exercises?|practice|worksheet|"
    r"задания|упражнения|практика|активности|"
    r"тапсырмалар|жаттығулар)\b",
    re.IGNORECASE,
)
_ASSESSMENT_TITLES = re.compile(
    r"^(?:\d+[.)]\s*)?(?:knowledge\s+check|self[-\s]?check|quiz|test|questions?|"
    r"assessment|suggested\s+answers?|answer\s+key|"
    r"проверка\s+знаний|тест|викторина|вопросы|ответы|ключи|"
    r"білімді\s+тексеру|тест|сұрақтар|жауаптар)\b",
    re.IGNORECASE,
)
_REFERENCE_TITLES = re.compile(
    r"^(?:\d+[.)]\s*)?(?:glossary|key\s+terms|terminology|vocabulary|definitions|"
    r"глоссарий|термины|словарь|"
    r"глоссарий|терминдер)\b",
    re.IGNORECASE,
)
_SCAFFOLD_TITLES = re.compile(
    r"^(?:\d+[.)]\s*)?(?:how\s+to\s+use|about\s+this\s+lesson|final\s+takeaway|"
    r"metadata|document\s+information|"
    r"как\s+пользоваться|итоги|итог|"
    r"қалай\s+пайдалану|қорытынды)\b",
    re.IGNORECASE,
)
_SCAFFOLD_TEXT = re.compile(
    r"(?:how\s+to\s+use\s+this\s+lesson|estimated\s+time|designed\s+for|"
    r"как\s+пользоваться\s+этим\s+уроком|"
    r"осы\s+сабақты\s+қалай\s+пайдалану)",
    re.IGNORECASE,
)
_METADATA_TITLES = re.compile(
    r"^(?:level|estimated\s+time|format|designed\s+for|audience|duration|"
    r"difficulty|prerequisites?|уровень|время|формат|для\s+кого)\s*$",
    re.IGNORECASE,
)
_REFERENCE_TEXT = re.compile(
    r"^(?:term\s+(?:meaning|definition)|term\s*[—–-]\s*definition)",
    re.IGNORECASE,
)
_OBJECTIVE_INTRO = re.compile(
    r"^(?:by\s+the\s+end|after\s+this\s+lesson|you\s+should\s+be\s+able|"
    r"students?\s+will\s+be\s+able|в\s+конце|по\s+итогам|"
    r"осы\s+сабақтан\s+кейін)",
    re.IGNORECASE,
)
_BULLET_SPLIT = re.compile(r"[\n•●▪◦\u2022]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _title(section: DocumentSection) -> str:
    return normalize_text(section.title)


def classify_section(section: DocumentSection) -> SectionKind:
    """Return the role of one section based on its heading and opening text."""
    title = _title(section)
    if _REFERENCE_TITLES.search(title) or _REFERENCE_TEXT.search(title):
        return "reference"
    if _OBJECTIVE_TITLES.search(title):
        return "objectives"
    if _ACTIVITY_TITLES.search(title):
        return "activities"
    if _ASSESSMENT_TITLES.search(title):
        return "activities"
    if _SCAFFOLD_TITLES.search(title) or _METADATA_TITLES.search(title):
        return "scaffold"
    opening = normalize_text(section.text)[:400]
    if _REFERENCE_TEXT.search(opening):
        return "reference"
    if _SCAFFOLD_TEXT.search(opening):
        return "scaffold"
    if (
        section.page_start == 1
        and section.level <= 1
        and len(section.text) < 260
        and section.title.isupper()
        and len(section.title.split()) <= 7
    ):
        return "scaffold"
    return "content"


def _clean_objective(text: str) -> str:
    text = text.strip(" \t-–—•●▪◦")
    text = re.sub(r"^\d+[.)]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:260]


def extract_objectives(sections: list[DocumentSection]) -> list[str]:
    """Collect objective bullets for coverage prompting/validation."""
    objectives: list[str] = []
    seen: set[str] = set()
    for section in sections:
        if section.kind != "objectives":
            continue
        pieces: list[str] = []
        for block in section.text.split("\n\n"):
            pieces.extend(_BULLET_SPLIT.split(block))
        for piece in pieces:
            for sentence in _SENTENCE_SPLIT.split(piece):
                cleaned = _clean_objective(sentence)
                if len(cleaned) < 18 or len(cleaned) > 240:
                    continue
                if _OBJECTIVE_INTRO.search(cleaned):
                    continue
                key = cleaned.casefold()
                if key in seen:
                    continue
                seen.add(key)
                objectives.append(cleaned)
    return objectives[:24]


def classify_sections(
    sections: list[DocumentSection],
) -> tuple[list[DocumentSection], list[str]]:
    """Return sections with ``kind`` filled in plus the objectives checklist."""
    classified: list[DocumentSection] = []
    glossary_mode = False
    for section in sections:
        kind = classify_section(section)
        if glossary_mode and kind == "content":
            if section.level <= 1:
                glossary_mode = False
            elif len(section.text) <= 450:
                kind = "reference"
        if kind in {"objectives", "activities", "scaffold"}:
            glossary_mode = False
        if kind == "reference":
            glossary_mode = True
        classified.append(section.model_copy(update={"kind": kind}))
    objectives = extract_objectives(classified)
    return classified, objectives


def page_text_map(sections: list[DocumentSection]) -> dict[int, str]:
    """Build a page → text map for grounding checks and repair excerpts."""
    pages: dict[int, list[str]] = {}
    for section in sections:
        if section.blocks:
            for block in section.blocks:
                pages.setdefault(block.page, []).append(block.text)
        elif section.text:
            for page in range(section.page_start, section.page_end + 1):
                pages.setdefault(page, []).append(section.text)
    return {page: "\n\n".join(parts) for page, parts in sorted(pages.items())}
