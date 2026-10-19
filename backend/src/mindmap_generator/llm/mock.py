"""Deterministic offline "LLM" used for demos and smoke tests.

It is a heuristic extractor, **not** a language model: it reads the grounded
material embedded in the pipeline prompts (document title, outline, chunk
summaries) and assembles a valid tree. Real generation requires a configured
provider. Kept intentionally simple and clearly labelled.
"""

from __future__ import annotations

import re
from typing import Any

from ..config import Settings
from .base import LLMClient

_OUTLINE_RE = re.compile(
    r"^- L(?P<level>[123]) \| pages (?P<start>\d+)(?:-(?P<end>\d+))? \| (?P<title>.+)$",
    re.MULTILINE,
)
_CHUNK_RE = re.compile(
    r"^### (?P<title>.+?) \(pages (?P<pages>[^)]+)\)\n"
    r"Summary: (?P<summary>.*?)\n"
    r"Concepts: (?P<concepts>.*?)\n"
    r"Key terms: (?P<terms>.*?)(?=\n### |\n\nBuild|\Z)",
    re.MULTILINE | re.DOTALL,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_STOPWORDS = {
    "this", "that", "with", "from", "have", "were", "which", "there", "their",
    "these", "those", "into", "also", "such", "more", "than", "been", "they",
    "will", "when", "what", "about", "other", "some", "each", "document",
    "section", "pages", "summary", "concepts", "terms", "using", "used",
}


def _field(prompt: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", prompt, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]


def _short_label(text: str, words: int = 5) -> str:
    text = re.sub(r"^(?:#+\s*|[-•]\s*)", "", text).strip(" .,:;—-")
    parts = text.split()
    if len(parts) > words:
        text = " ".join(parts[:words])
    return text[:80].strip()


def _keywords(text: str, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for word in _WORD_RE.findall(text.casefold()):
        if word in _STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], word))
    return [word.capitalize() for word in ranked[:limit]]


class MockLLMClient(LLMClient):
    """Heuristic stand-in that always returns schema-valid JSON."""

    provider = "mock"
    model = "mock-heuristic-v1"

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
        if schema_name == "chunk_summary":
            return self._chunk_summary(user_prompt)
        return self._hierarchy(user_prompt)

    # -- map step ---------------------------------------------------------
    def _chunk_summary(self, prompt: str) -> dict[str, Any]:
        match = re.search(r"CHUNK TEXT:\s*<<<\s*(.*?)\s*>>>", prompt, re.DOTALL)
        text = match.group(1) if match else ""
        sentences = _sentences(text)
        pages_match = re.search(r"^PAGES:\s*(.+)$", prompt, re.MULTILINE)
        pages = [int(n) for n in re.findall(r"\d+", pages_match.group(1))] if pages_match else [1]
        concepts = []
        for sentence in sentences[:5]:
            label = _short_label(sentence)
            if label:
                concepts.append(
                    {
                        "label": label,
                        "summary": sentence[:220],
                        "source_pages": pages[:2] or [1],
                    }
                )
        if not concepts:
            concepts = [{"label": "Content", "summary": text[:220], "source_pages": pages[:1]}]
        return {
            "summary": " ".join(sentences[:2])[:400] or text[:300],
            "key_concepts": concepts,
            "key_terms": _keywords(text, 10),
        }

    # -- reduce step ------------------------------------------------------
    def _hierarchy(self, prompt: str) -> dict[str, Any]:
        title = _field(prompt, "DOCUMENT TITLE") or "Document"
        page_count = int(_field(prompt, "DOCUMENT PAGES") or 1)
        max_branches = int(re.search(r"MAIN BRANCHES: \d+-(\d+)", prompt).group(1)) if re.search(
            r"MAIN BRANCHES: \d+-(\d+)", prompt
        ) else 6
        max_branches = max(2, min(max_branches, 8))

        outline = [
            {
                "level": int(match.group("level")),
                "start": int(match.group("start")),
                "end": int(match.group("end") or match.group("start")),
                "title": match.group("title").strip(),
            }
            for match in _OUTLINE_RE.finditer(prompt)
        ]
        chunks = [
            {
                "title": match.group("title").strip(),
                "pages": [int(n) for n in re.findall(r"\d+", match.group("pages"))],
                "summary": re.sub(r"\s+", " ", match.group("summary")).strip(),
                "concepts": [
                    concept.strip()
                    for concept in match.group("concepts").split(";")
                    if concept.strip()
                ],
                "terms": [
                    term.strip()
                    for term in match.group("terms").split(",")
                    if term.strip()
                ],
            }
            for match in _CHUNK_RE.finditer(prompt)
        ]

        text_match = re.search(r"DOCUMENT TEXT:\s*<<<\s*(.*?)\s*>>>", prompt, re.DOTALL)
        body = text_match.group(1) if text_match else ""
        sentences = _sentences(body)
        terms = _keywords(body, 20) if body else []

        sections = self._sections_from_text(body)
        section_texts = {title: text for title, text in sections}
        all_text = " ".join(text for _, text in sections) or body
        sentences = _sentences(all_text) or _sentences(body)
        terms = _keywords(all_text, 24) if all_text else []

        main_sections = [entry for entry in outline if entry["level"] == 1]
        if len(main_sections) < 4:
            # With few top-level headings, use the full outline so the demo
            # still shows a useful breadth of branches.
            main_sections = list(outline)
        if len(main_sections) < 2:
            main_sections = []
            keyword_pool = terms or ["Overview", "Details", "Context"]
            for keyword in keyword_pool[:max_branches]:
                main_sections.append(
                    {"level": 1, "start": 1, "end": page_count, "title": keyword}
                )

        selected = main_sections[:max_branches]
        if len(selected) < 2:
            selected = [
                {"level": 1, "start": 1, "end": page_count, "title": "Overview"},
                {"level": 1, "start": 1, "end": page_count, "title": "Details"},
            ]

        branches: list[dict[str, Any]] = []
        for position, entry in enumerate(selected):
            branch_title = _short_label(entry["title"], 6) or "Theme"
            matching_chunk = next(
                (chunk for chunk in chunks if chunk["title"] == entry["title"]), None
            )
            section_text = section_texts.get(entry["title"], "")
            section_sentences = _sentences(section_text)
            children: list[dict[str, Any]] = []
            seen_labels: set[str] = set()

            def add_child(
                label: str,
                summary: str,
                pages: list[int],
                *,
                _children: list[dict[str, Any]] = children,
                _seen: set[str] = seen_labels,
                _entry: dict[str, Any] = entry,
            ) -> None:
                cleaned = _short_label(label, 6)
                key = cleaned.casefold()
                if not cleaned or key in _seen:
                    return
                _seen.add(key)
                _children.append(
                    {
                        "label": cleaned,
                        "summary": summary[:240],
                        "source_pages": pages or [_entry["start"]],
                        "children": [],
                    }
                )

            if matching_chunk:
                for concept in matching_chunk["concepts"][:4]:
                    add_child(
                        concept.split(" — ")[0],
                        concept,
                        [entry["start"]],
                    )

            for sentence in section_sentences[:5]:
                if len(children) >= 4:
                    break
                add_child(sentence, sentence, [entry["start"]])

            if len(children) < 2:
                rotated = terms[position:] + terms[:position]
                for keyword in rotated[:4]:
                    if len(children) >= 3:
                        break
                    add_child(
                        keyword,
                        f"{keyword} is discussed in {branch_title} "
                        f"(pages {entry['start']}-{entry['end']}).",
                        [entry["start"]],
                    )

            summary = ""
            if matching_chunk and matching_chunk["summary"]:
                summary = matching_chunk["summary"][:240]
            elif section_sentences:
                summary = " ".join(section_sentences[:2])[:240]
            elif sentences:
                summary = sentences[position % len(sentences)][:240]
            else:
                summary = (
                    f"{branch_title} is discussed on pages "
                    f"{entry['start']}-{entry['end']}."
                )

            branches.append(
                {
                    "label": branch_title,
                    "summary": summary,
                    "source_pages": list(range(entry["start"], entry["end"] + 1))[:4],
                    "children": children[:4],
                }
            )

        if sentences:
            root_summary = " ".join(sentences[:2])[:300]
        elif chunks:
            root_summary = " ".join(chunk["summary"] for chunk in chunks[:2])[:300]
        else:
            root_summary = f"A mind map of {title}."
        return {
            "label": _short_label(title, 8) or "Document",
            "summary": root_summary,
            "source_pages": [1],
            "children": branches,
        }

    @staticmethod
    def _sections_from_text(body: str) -> list[tuple[str, str]]:
        """Parse the ``## Section`` blocks embedded in the single-call prompt."""
        matches = list(re.finditer(r"^## (.+?)\s*$", body, re.MULTILINE))
        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections.append((match.group(1).strip(), body[start:end].strip()))
        return sections
