"""Deterministic offline "LLM" used for demos and smoke tests.

It is a heuristic extractor, **not** a language model. It reads the grounded
material embedded in the pipeline prompts and produces schema-valid concept
cards and a category plan. Real generation requires a configured provider.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from ..config import Settings
from .base import LLMClient

_FIELD_RE = re.compile(r"^{name}:\s*(.+)$", re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_OBJECTIVE_START = re.compile(
    r"^(?:explain|describe|distinguish|identify|name|give|write|list|compare|"
    r"analy[sz]e|discuss|define|outline|summari[sz]e|apply|evaluate|"
    r"объясни|опиши|назови|перечисли|сравни|определи|түсіндір|сипатта|ата)\b",
    re.IGNORECASE,
)
_META = re.compile(
    r"\b(?:learning objectives?|by the end|students? will|you should be able|"
    r"this (?:section|lesson|document) (?:explains|describes|covers)|"
    r"how to use this lesson|estimated time|designed for|"
    r"цели? обучения|оқу мақсаттары)\b",
    re.IGNORECASE,
)
_ARTICLES = {"the", "a", "an", "this", "that", "these", "those", "it", "they", "we", "you"}
_TRANSITIONS = {
    "however", "during", "these", "those", "this", "many", "some", "most",
    "another", "for", "example", "remember", "there", "here", "then", "when",
    "while", "because", "if", "as", "also", "models", "methods", "systems",
    "processing", "sources", "repetition", "depending", "once", "each",
}
_BULLET_PREFIX = re.compile(r"^(?:[•●▪◦\-–—]\s*)+")
_VERBS = {
    "is", "are", "was", "were", "be", "been", "being", "can", "could", "will",
    "would", "should", "may", "might", "must", "has", "have", "had", "does",
    "do", "did", "converts", "occurs", "produces", "fixes", "uses", "helps",
    "allows", "means", "refers", "includes", "requires", "splits", "releases",
    "informs", "aims", "happens", "works", "provides", "generates", "processes",
    "learns", "predicts", "contains", "supports", "creates", "explains",
}
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "can", "could", "will", "would", "should", "may",
    "might", "must", "not", "but", "you", "your", "they", "their", "them",
    "its", "into", "about", "over", "under", "more", "most", "some", "such",
    "than", "then", "when", "where", "which", "who", "what", "how", "why",
    "all", "any", "each", "also", "very", "just", "only", "because", "while",
    "does", "did", "doing", "use", "used", "using", "make", "makes", "made",
    "like", "these", "those", "there", "here", "other", "another", "same",
    "different", "one", "two", "document", "section", "lesson", "page",
}
_INVENTORY_RE = re.compile(
    r"^- (?P<id>c\d+) \| (?P<term>[^|]+?) \| (?P<explanation>[^|]+?) \| pages (?P<pages>.+)$",
    re.MULTILINE,
)
_CATEGORY_POOL = [
    "Core Concepts",
    "How It Works",
    "Common Uses",
    "Key Considerations",
    "Practical Guidance",
    "Further Topics",
    "Context and Background",
    "Implications",
]


def _field(prompt: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", prompt, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in _SENTENCE_SPLIT.split(cleaned) if part.strip()]


def _short_label(text: str, words: int = 5) -> str:
    text = re.sub(r"^(?:#+\s*|[-•●▪◦]\s*)", "", text).strip(" .,:;—-")
    parts = text.split()
    if len(parts) > words:
        text = " ".join(parts[:words])
    return text[:80].strip()


def _clean_sentence(sentence: str) -> str:
    return _BULLET_PREFIX.sub("", sentence).strip()


def _term_from_sentence(sentence: str) -> str:
    sentence = _BULLET_PREFIX.sub("", sentence)
    words = re.findall(r"[^\s]+", sentence.strip(" \"'“”‘’.,:;"))
    while words and re.sub(r"\W", "", words[0]).casefold() in _ARTICLES:
        words.pop(0)
    chosen: list[str] = []
    for word in words:
        bare = re.sub(r"\W", "", word).casefold()
        if bare in _VERBS:
            if chosen:
                break
            continue
        if bare and bare not in _ARTICLES and bare not in _STOPWORDS:
            if not chosen and bare in _TRANSITIONS:
                continue
            chosen.append(word)
        if len(chosen) >= 3:
            break
    term = " ".join(chosen).strip(" .,:;—-")
    term = _short_label(term, 4)
    if len(term) < 3:
        term = _short_label(sentence, 3)
    return term


def _trim_words(text: str, limit: int = 28) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(" ,;:") + "."


def _keywords(text: str, limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for word in _WORD_RE.findall(text.casefold()):
        if word in _STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], word))
    return [word.capitalize() for word in ranked[:limit]]


class MockLLMClient(LLMClient):
    """Heuristic stand-in that returns schema-valid JSON for offline demos."""

    provider = "mock"
    model = "mock-heuristic-v2"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self.calls: list[str] = []

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str = "response",
    ) -> dict[str, Any]:
        self.calls.append(schema_name)
        if schema_name == "concept_extraction":
            return self._concept_extraction(user_prompt)
        if schema_name == "concept_repair":
            return self._concept_repair(user_prompt)
        if schema_name in {"cluster", "cluster_repair"}:
            return self._cluster(user_prompt)
        return {}

    # -- concept extraction ------------------------------------------------
    def _concept_extraction(self, prompt: str) -> dict[str, Any]:
        section = _field(prompt, "SECTION") or "Document"
        section_kind = _field(prompt, "SECTION ROLE") or "content"
        pages_match = re.search(r"^PAGES:\s*(.+)$", prompt, re.MULTILINE)
        pages = [int(n) for n in re.findall(r"\d+", pages_match.group(1))] if pages_match else [1]
        text_match = re.search(r"SECTION TEXT:\s*<<<\s*(.*?)\s*>>>", prompt, re.DOTALL)
        text = text_match.group(1) if text_match else ""
        sentences = [
            _clean_sentence(sentence)
            for sentence in _sentences(text)
            if 35 <= len(_clean_sentence(sentence)) <= 300
            and not _OBJECTIVE_START.search(_clean_sentence(sentence))
            and not _META.search(_clean_sentence(sentence))
        ]
        concepts: list[dict[str, Any]] = []
        seen: set[str] = set()
        if section_kind == "reference":
            term = _short_label(section.replace("Term Meaning", ""), 4)
            if term and term.casefold() not in {"glossary", "key terms", "terminology"}:
                definition = _trim_words(sentences[0] if sentences else text[:260])
                concepts.append(
                    {
                        "term": term,
                        "explanation": definition,
                        "evidence": (sentences[0] if sentences else text)[:220],
                        "source_pages": pages[:2] or [1],
                    }
                )
        for sentence in sentences[:4]:
            term = _term_from_sentence(sentence)
            key = term.casefold()
            if not term or key in seen or key in _TRANSITIONS:
                continue
            seen.add(key)
            concepts.append(
                {
                    "term": term,
                    "explanation": _trim_words(sentence),
                    "evidence": sentence[:220],
                    "source_pages": pages[:2] or [1],
                }
            )
        if not concepts:
            fallback = _short_label(section, 4) or "Key idea"
            concepts.append(
                {
                    "term": fallback,
                    "explanation": _trim_words(text[:280] or "The section describes the topic."),
                    "evidence": text[:220],
                    "source_pages": pages[:2] or [1],
                }
            )
        return {"concepts": concepts}

    # -- clustering --------------------------------------------------------
    def _cluster(self, prompt: str) -> dict[str, Any]:
        title = _field(prompt, "DOCUMENT TITLE") or "Document"
        inventory = [
            {"id": match.group("id"), "term": match.group("term").strip()}
            for match in _INVENTORY_RE.finditer(prompt)
        ]
        if not inventory:
            inventory = [
                {"id": match.group(1), "term": match.group(2).strip()}
                for match in re.finditer(r"^- (c\d+) \| ([^|]+?) \|", prompt, re.MULTILINE)
            ]
        if not inventory:
            return {"root_label": title, "categories": []}
        max_branches_match = re.search(r"MAX MAIN CATEGORIES:\s*(\d+)", prompt)
        max_branches = int(max_branches_match.group(1)) if max_branches_match else 6
        total = len(inventory)
        if total >= 12:
            minimum = 4
        elif total >= 6:
            minimum = 3
        elif total >= 4:
            minimum = 2
        else:
            minimum = 1
        category_count = max(minimum, min(max_branches, 8, math.ceil(total / 3)))
        category_count = min(category_count, max(1, total // 2))
        base, extra = divmod(total, category_count)
        group_names = ["Overview", "Details", "Examples", "Context"]
        categories: list[dict[str, Any]] = []
        index = 0
        for position in range(category_count):
            take = base + (1 if position < extra else 0)
            ids = [item["id"] for item in inventory[index : index + take]]
            index += take
            if not ids:
                break
            label = _CATEGORY_POOL[position % len(_CATEGORY_POOL)]
            if len(ids) <= 6:
                groups = [{"label": "", "concept_ids": ids}]
            else:
                groups = [
                    {
                        "label": group_names[group_position // 5 % len(group_names)],
                        "concept_ids": ids[group_position : group_position + 5],
                    }
                    for group_position in range(0, len(ids), 5)
                ]
            categories.append({"label": label, "groups": groups})
        return {"root_label": title, "categories": categories}

    # -- concept repair ----------------------------------------------------
    def _concept_repair(self, prompt: str) -> dict[str, Any]:
        match = re.search(r"INVALID CONCEPTS:\s*<<<\s*(.*?)\s*>>>", prompt, re.DOTALL)
        cards: list[dict[str, Any]] = []
        if match:
            try:
                cards = json.loads(match.group(1))
            except json.JSONDecodeError:
                cards = []
        repaired: list[dict[str, Any]] = []
        for card in cards:
            term = str(card.get("term", "Concept")).strip() or "Concept"
            evidence = str(card.get("evidence", "")).strip()
            explanation = (
                evidence
                if len(evidence.split()) >= 5
                else f"{term} is described in the source text."
            )
            repaired.append(
                {
                    "id": card.get("id", ""),
                    "term": term,
                    "explanation": _trim_words(explanation),
                    "evidence": evidence,
                    "source_pages": card.get("source_pages") or [1],
                }
            )
        return {"concepts": repaired}
