"""Text cleanup: whitespace, hyphenation, repeated headers/footers, page numbers."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from math import ceil

from .types import RawLine

# Space/tab runs, but never newlines.
_SPACE_RE = re.compile(r"[^\S\n]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
# A hyphen/soft-hyphen at end of a line that continues a word.
_HYPHEN_BREAK_RE = re.compile(r"(?<=[^\W\d_])[-\u00ad\u2010\u2011][ \t]*\n[ \t]*(?=[^\W\d_])")
_ANY_BREAK_RE = re.compile(r"[ \t]*\n[ \t]*")
_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s*)?[-–—]?\s*\d{1,4}\s*(?:(?:/|of)\s*\d{1,4})?\s*[-–—]?\s*$",
    re.IGNORECASE,
)
_ROMAN_PAGE_RE = re.compile(r"^\s*[ivxlcdm]{1,7}\s*$", re.IGNORECASE)
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}


def normalize_unicode(text: str) -> str:
    """Normalize compatibility forms without removing script information."""
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    return text


def clean_line(text: str) -> str:
    """Collapse inline whitespace and trim one extracted line."""
    text = normalize_unicode(text).replace("\u00ad", "")
    return _SPACE_RE.sub(" ", text).strip()


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines, repairing end-of-line hyphenation."""
    if not lines:
        return ""
    text = "\n".join(lines)
    text = _HYPHEN_BREAK_RE.sub("", text)
    text = _ANY_BREAK_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_text(text: str) -> str:
    """Normalize a multi-paragraph text block in place-preserving way."""
    text = normalize_unicode(text)
    text = _ANY_BREAK_RE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return _SPACE_RE.sub(" ", text).strip()


def is_page_number(text: str) -> bool:
    """Return True for stand-alone page-number lines."""
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_PAGE_NUMBER_RE.match(stripped) or _ROMAN_PAGE_RE.match(stripped))


def _repeat_key(text: str) -> str:
    """Normalize a header/footer candidate so changing numbers still match."""
    key = clean_line(text).casefold()
    key = re.sub(r"\d+", "#", key)
    return re.sub(r"\s+", " ", key).strip()


def remove_boilerplate(pages: list[list[RawLine]]) -> int:
    """Remove repeated running headers/footers and page numbers in place.

    Only lines near the top/bottom of each page are considered candidates.
    A candidate must occur on at least half of the pages (minimum 3) to count
    as a running header/footer.

    Returns the number of removed lines.
    """
    if len(pages) < 3:
        # Still remove obvious page-number lines even in tiny documents.
        removed = 0
        for lines in pages:
            before = len(lines)
            lines[:] = [line for line in lines if not is_page_number(line.text)]
            removed += before - len(lines)
        return removed

    counts: Counter[str] = Counter()
    for lines in pages:
        ordered = sorted(lines, key=lambda line: (line.y, line.text))
        candidates = ordered[:2] + ordered[-2:]
        seen: set[str] = set()
        for line in candidates:
            key = _repeat_key(line.text)
            if key and len(key) <= 120 and key not in seen:
                seen.add(key)
                counts[key] += 1

    threshold = max(3, ceil(len(pages) * 0.5))
    repeated = {key for key, count in counts.items() if count >= threshold}

    removed = 0
    for lines in pages:
        kept: list[RawLine] = []
        for line in lines:
            if is_page_number(line.text) or _repeat_key(line.text) in repeated:
                removed += 1
                continue
            kept.append(line)
        lines[:] = kept
    return removed


def truncate_at_sentence(text: str, limit: int) -> str:
    """Trim text to ``limit`` chars, preferring a sentence/word boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut >= limit // 2:
        return window[: cut + 1].strip()
    cut = window.rfind(" ")
    if cut > 0:
        return window[:cut].rstrip(" ,;:-") + "…"
    return window.rstrip() + "…"


def clean_label(text: str, max_words: int = 8, max_chars: int = 90) -> str:
    """Normalize a heading/node label and enforce short-label limits."""
    text = normalize_text(text)
    text = text.strip(" \t\r\n-–—•·.:;,")
    if not text:
        return ""
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    if len(text) > max_chars:
        text = text[:max_chars].rstrip(" ,;:-") + "…"
    return text
