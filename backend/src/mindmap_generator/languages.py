"""Language detection and prompt-language helpers.

This is intentionally a lightweight heuristic: no network calls and no extra
large dependency. It recognises scripts (Cyrillic, Arabic, CJK) reliably and
uses small stop-word lists for common Latin-script languages.
"""

from __future__ import annotations

import re
from collections import Counter

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ru": "Russian",
    "kk": "Kazakh",
    "uk": "Ukrainian",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

# Letters that only occur in Kazakh within common Cyrillic-script languages.
KAZAKH_LETTERS = set("әғқңөұүһі")

_LATIN_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "in", "is", "that", "for", "with", "this", "are", "from"},
    "de": {"der", "die", "und", "das", "ist", "von", "mit", "den", "sich", "auf", "für", "nicht"},
    "fr": {"les", "des", "est", "une", "dans", "pour", "que", "qui", "sur", "avec", "pas", "plus"},
    "es": {"los", "las", "una", "para", "con", "por", "que", "del", "como", "este", "más", "sus"},
    "pt": {"os", "das", "uma", "para", "com", "por", "que", "do", "como", "este", "mais", "não"},
    "it": {
        "gli", "una", "per", "con", "che", "del", "della", "sono", "come", "questo",
        "più", "non",
    },
}

_CYRILLIC_STOPWORDS: dict[str, set[str]] = {
    "ru": {"и", "в", "не", "на", "что", "это", "как", "для", "с", "по", "из", "к"},
    "uk": {"і", "в", "не", "на", "що", "це", "як", "для", "з", "по", "із", "до"},
    "kk": {"және", "бұл", "үшін", "болып", "мен", "де", "қазақ", "бір", "осы", "оның"},
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _letter_ratio(text: str, predicate) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if predicate(ch)) / len(letters)


def _score_stopwords(words: list[str], table: dict[str, set[str]]) -> tuple[str, int]:
    counts = Counter(words)
    scored = {lang: sum(counts[word] for word in stops) for lang, stops in table.items()}
    best_lang, best_score = max(scored.items(), key=lambda item: item[1])
    return best_lang, best_score


def detect_language(text: str) -> str:
    """Detect a document language from a conservative text sample.

    Returns an ISO-639-1 code. Falls back to ``en`` when there is not enough
    evidence (or when the text is mostly Latin script without clear stop words).
    """
    sample = text[:30000]
    if not sample.strip():
        return "en"

    cyrillic_ratio = _letter_ratio(sample, lambda ch: "\u0400" <= ch <= "\u04ff")
    arabic_ratio = _letter_ratio(sample, lambda ch: "\u0600" <= ch <= "\u06ff")
    kana_ratio = _letter_ratio(sample, lambda ch: "\u3040" <= ch <= "\u30ff")
    hangul_ratio = _letter_ratio(sample, lambda ch: "\uac00" <= ch <= "\ud7af")
    han_ratio = _letter_ratio(sample, lambda ch: "\u4e00" <= ch <= "\u9fff")

    if kana_ratio > 0.05:
        return "ja"
    if hangul_ratio > 0.1:
        return "ko"
    if han_ratio > 0.2:
        return "zh"
    if arabic_ratio > 0.2:
        return "ar"

    words = [w.casefold() for w in _WORD_RE.findall(sample)]
    word_set = set(words)

    if cyrillic_ratio > 0.2:
        if len(KAZAKH_LETTERS & set(sample.casefold())) >= 2:
            return "kk"
        best, score = _score_stopwords(words, _CYRILLIC_STOPWORDS)
        if score >= 3:
            return best
        return "ru"

    best, score = _score_stopwords(words, _LATIN_STOPWORDS)
    if score >= 4:
        return best
    # "A" and "I" are weak signals but better than nothing for short texts.
    if {"the", "and", "of"} & word_set:
        return "en"
    return "en"


def language_name(code: str | None) -> str:
    """Human-readable language name used inside prompts."""
    if not code:
        return "the document's language"
    return LANGUAGE_NAMES.get(code.lower(), code)


def resolve_output_language(document_language: str, override: str | None) -> str:
    """Pick the requested language or fall back to the document language."""
    if override:
        return override.strip().lower()
    return document_language or "en"
