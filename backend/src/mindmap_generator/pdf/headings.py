"""Heading detection: PDF outline > font/size heuristics > numbering patterns."""

from __future__ import annotations

import re
from collections import Counter

from .clean import clean_label, normalize_text
from .types import Heading, OutlineEntry, Paragraph

_NUMBERED_RE = re.compile(
    r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})[.)]?[ \t]+(?P<title>[^\s].*)$",
)
_CHAPTER_RE = re.compile(
    r"^(?P<kind>chapter|part|section|appendix|глава|раздел|бөлім|тарау)\s+"
    r"(?P<num>[\divxlcdm]+)\b[\s.:–—-]*(?P<title>.*)$",
    re.IGNORECASE,
)
_ALNUM_RE = re.compile(r"[^\W_]", re.UNICODE)
_DIGIT_RE = re.compile(r"\d")


def _starts_upper(text: str) -> bool:
    for char in text:
        if char.isalpha():
            return char.isupper()
    return False


def numbering_heading(text: str) -> tuple[str, int] | None:
    """Extract a heading title/level from common numbering patterns.

    Examples: ``1. Introduction``, ``2.3 Results``, ``Chapter 4: Methods``,
    ``Глава 2. Обзор``. Returns ``None`` when the line is not heading-like.
    """
    stripped = normalize_text(text)
    if not stripped or len(stripped) > 120:
        return None

    chapter = _CHAPTER_RE.match(stripped)
    if chapter:
        title = clean_label(chapter.group("title")) or clean_label(stripped)
        return title, 1

    match = _NUMBERED_RE.match(stripped)
    if not match:
        return None
    title = match.group("title").strip()
    if len(title) < 2 or len(title) > 90:
        return None
    # Reject sentence fragments / list prose: headings do not end with a period
    # unless they are extremely short, and they normally start capitalized.
    if title.endswith((".", ";", ":")) and len(title.split()) > 3:
        return None
    if title.endswith((",",)):
        return None
    if not _starts_upper(title) and title[0].isalpha():
        return None
    if sum(1 for ch in title if ch.isalpha()) < 2:
        return None
    level = 1 + match.group("num").count(".")
    return clean_label(title), min(level, 3)


def estimate_body_size(paragraphs: list[Paragraph]) -> float:
    """Estimate the dominant body font size from longer paragraphs."""
    sizes = [round(p.size, 1) for p in paragraphs if len(p.text) >= 60 and p.size > 0]
    if not sizes:
        sizes = [round(p.size, 1) for p in paragraphs if p.size > 0]
    if not sizes:
        return 0.0
    return Counter(sizes).most_common(1)[0][0]


def _paragraph_looks_heading(paragraph: Paragraph, body_size: float) -> bool:
    text = paragraph.text.strip()
    if not (3 <= len(text) <= 120):
        return False
    if text.endswith((".", ";", ",")):
        return False
    if len(text.split()) > 16:
        return False
    if not _starts_upper(text) and text[0].isalpha():
        return False
    if len(_ALNUM_RE.findall(text)) < 2:
        return False
    digit_ratio = len(_DIGIT_RE.findall(text)) / max(len(text), 1)
    if digit_ratio > 0.35:
        return False
    ratio = paragraph.size / body_size if body_size else 0.0
    return ratio >= 1.12 or (paragraph.bold and ratio >= 0.97 and len(text) <= 90)


def font_headings(paragraphs: list[Paragraph]) -> list[Heading]:
    """Detect headings from font size/bold information and rank their levels."""
    body_size = estimate_body_size(paragraphs)
    candidates: list[tuple[int, float]] = []
    for index, paragraph in enumerate(paragraphs):
        if _paragraph_looks_heading(paragraph, body_size):
            candidates.append((index, round(paragraph.size, 1)))

    # Rank distinct font sizes: largest is level 1, then 2, then 3.
    sizes = sorted({size for _, size in candidates if size > 0}, reverse=True)
    rank = {size: min(position + 1, 3) for position, size in enumerate(sizes)}

    headings: list[Heading] = []
    for index, size in candidates:
        paragraph = paragraphs[index]
        level = rank.get(size, 3)
        if size == 0 or not sizes:
            level = 3
        headings.append(
            Heading(
                index=index,
                title=clean_label(paragraph.text),
                level=max(1, min(level, 3)),
                page=paragraph.page,
            )
        )
    return headings


def _match_key(text: str) -> str:
    return re.sub(r"[^\w]+", "", normalize_text(text).casefold())


def outline_headings(paragraphs: list[Paragraph], outline: list[OutlineEntry]) -> list[Heading]:
    """Map PDF bookmark titles onto paragraph indices."""
    by_page: dict[int, list[int]] = {}
    for index, paragraph in enumerate(paragraphs):
        by_page.setdefault(paragraph.page, []).append(index)

    headings: list[Heading] = []
    lower_bound = 0
    for entry in outline:
        page_indices = [idx for idx in by_page.get(entry.page, []) if idx >= lower_bound]
        target = _match_key(entry.title)
        chosen: int | None = None
        if target:
            for idx in page_indices:
                candidate = _match_key(paragraphs[idx].text)
                if not candidate:
                    continue
                if candidate == target or (len(target) >= 5 and target in candidate):
                    chosen = idx
                    break
        if chosen is None and page_indices:
            chosen = page_indices[0]
        if chosen is None:
            continue
        headings.append(
            Heading(
                index=chosen,
                title=clean_label(entry.title),
                level=max(1, min(entry.level, 3)),
                page=paragraphs[chosen].page,
            )
        )
        lower_bound = chosen

    # Remove duplicate anchors while preserving order.
    unique: list[Heading] = []
    seen: set[tuple[int, int]] = set()
    for heading in headings:
        key = (heading.index, heading.level)
        if key in seen:
            continue
        seen.add(key)
        unique.append(heading)
    return unique


def detect_headings(
    paragraphs: list[Paragraph], outline: list[OutlineEntry]
) -> tuple[list[Heading], bool]:
    """Detect headings using the required priority order.

    Returns ``(headings, outline_used)``. When no heading is found the caller
    falls back to a single whole-document section.
    """
    if len(outline) >= 2:
        mapped = outline_headings(paragraphs, outline)
        if mapped:
            return mapped, True

    numbered: dict[int, Heading] = {}
    for index, paragraph in enumerate(paragraphs):
        parsed = numbering_heading(paragraph.text)
        if parsed:
            title, level = parsed
            numbered[index] = Heading(index=index, title=title, level=level, page=paragraph.page)

    font = {heading.index: heading for heading in font_headings(paragraphs)}

    # If font heuristics flag an implausible share of paragraphs (slide decks,
    # cover pages), trust numbering only.
    if len(paragraphs) and len(font) > 10 and len(font) > len(paragraphs) * 0.65:
        font = {}

    combined: dict[int, Heading] = {}
    for index in sorted(set(numbered) | set(font)):
        combined[index] = numbered.get(index) or font[index]

    headings = sorted(combined.values(), key=lambda heading: heading.index)
    if len(headings) < 2 and len(font) >= 2:
        headings = sorted(font.values(), key=lambda heading: heading.index)
    return headings, False
