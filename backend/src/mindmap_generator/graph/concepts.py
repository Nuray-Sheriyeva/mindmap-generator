"""Grounded concept cards: cleaning, dedupe, evidence and style helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import ConceptCard
from ..pdf.clean import clean_label, normalize_text

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "can", "could", "will", "would", "should", "may", "might", "must",
    "not", "but", "you", "your", "they", "their", "them", "its", "it's", "into",
    "about", "over", "under", "more", "most", "some", "such", "than", "then",
    "when", "where", "which", "who", "what", "how", "why", "all", "any", "each",
    "also", "very", "just", "only", "because", "while", "does", "did", "doing",
    "use", "used", "using", "make", "makes", "made", "like", "these", "those",
    "there", "here", "other", "another", "same", "different", "one", "two",
    "и", "в", "не", "на", "что", "это", "как", "для", "с", "по", "из", "к",
    "және", "бұл", "үшін", "мен", "де", "бір", "осы",
}

_IMPERATIVE_EN = re.compile(
    r"^(?:explain|describe|distinguish|identify|name|give|write|list|compare|"
    r"analy[sz]e|discuss|define|outline|summari[sz]e|state|apply|evaluate|"
    r"create|design|demonstrate|illustrate|recognize|understand)\b",
    re.IGNORECASE,
)
_IMPERATIVE_RU = re.compile(
    r"^(?:объясни|объясните|опиши|опишите|назови|назовите|перечисли|перечислите|"
    r"сравни|сравните|определи|определите|охарактеризуй|охарактеризуйте|"
    r"проанализируй|проанализируйте|сформулируй|сформулируйте)\b",
    re.IGNORECASE,
)
_IMPERATIVE_KK = re.compile(
    r"^(?:түсіндір|түсіндіріңіз|сипатта|сипаттаңыз|ата|атаңыз|салыстыр|"
    r"салыстырыңыз|анықта|анықтаңыз)\b",
    re.IGNORECASE,
)
_CYRILLIC_LANGS = {"ru", "kk", "uk", "bg", "sr", "mk", "be"}
_CJK_LANGS = {"zh", "ja", "ko"}
_LANG_SCRIPT_HINTS = {
    "ru": "Cyrillic",
    "kk": "Cyrillic",
    "uk": "Cyrillic",
    "bg": "Cyrillic",
    "sr": "Cyrillic",
    "mk": "Cyrillic",
    "be": "Cyrillic",
    "zh": "Chinese characters",
    "ja": "Japanese characters",
    "ko": "Korean characters",
    "ar": "Arabic script",
}
_META_PHRASES = re.compile(
    r"\b(?:by the end of (?:this|the) lesson|learning objectives?|lesson objectives?|"
    r"students? will|you should be able|this (?:section|lesson|document) "
    r"(?:explains|describes|covers)|the (?:document|text) (?:says|states|explains)|"
    r"in this (?:section|lesson)|the goal of this|the purpose of this|"
    r"цели? обучения|в этом (?:разделе|уроке)|студенты будут|"
    r"оқу мақсаттары|осы (?:бөлімде|сабақта))\b",
    re.IGNORECASE,
)
_GENERIC_TERMS = {
    "model", "models", "usually", "example", "examples", "mechanism", "mechanisms",
    "system", "systems", "method", "methods", "process", "processing", "information",
    "data", "concept", "concepts", "topic", "topics", "overview", "introduction",
    "summary", "conclusion", "details", "large", "however", "during", "things",
    "idea", "ideas", "part", "parts", "way", "ways", "approach", "approaches",
    "text", "document", "section", "lesson",
}
_SCAFFOLD_TERM = re.compile(
    r"^(?:learning\s+objectives?|lesson\s+objectives?|objectives?|goals?|"
    r"activities|activity|knowledge\s+check|self[-\s]?check|quiz|"
    r"suggested\s+answers?|answer\s+key|glossary|key\s+terms|terminology|"
    r"how\s+to\s+use.*|final\s+takeaway|metadata|"
    r"цели\s+обучения|задачи\s+урока|задания|упражнения|проверка\s+знаний|"
    r"ответы|глоссарий|как\s+пользоваться|итоги|"
    r"оқу\s+мақсаттары|сабақ\s+мақсаттары|тапсырмалар|жауаптар|глоссарий|"
    r"қалай\s+пайдалану|қорытынды)$",
    re.IGNORECASE,
)
_LEADING_META = re.compile(
    r"^(?:explanation|definition|summary|meaning)\s*[:\-–—]\s*",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")


@dataclass
class MergedConcepts:
    """Deduplicated concepts plus merge notes."""

    concepts: list[ConceptCard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_term(value: str, *, max_words: int = 5, max_chars: int = 80) -> str:
    """Normalize a leaf term without losing technical wording."""
    term = clean_label(value, max_words=max_words, max_chars=max_chars)
    term = term.strip(" \"'`“”‘’.,:;")
    return term


def normalize_explanation(value: str, max_chars: int = 420) -> str:
    """Clean an explanation and remove common meta prefixes."""
    text = normalize_text(value)
    text = text.strip(" \"'`“”‘’")
    text = _LEADING_META.sub("", text).strip()
    text = re.sub(
        r"^(?:this (?:section|lesson|document) (?:explains|describes|covers) (?:that )?|"
        r"the (?:document|text) (?:says|states) (?:that )?)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return text


def content_words(text: str) -> list[str]:
    """Return lowercased content words used for grounding overlap."""
    words = re.findall(r"[^\W_]{3,}", text.casefold(), flags=re.UNICODE)
    return [word for word in words if word not in _STOPWORDS]


def style_errors(
    term: str,
    explanation: str,
    *,
    min_words: int = 5,
    max_words: int = 32,
) -> list[str]:
    """Return style errors that indicate task/objective language or bad length."""
    errors: list[str] = []
    normalized = explanation.strip()
    words = normalized.split()
    if not term.strip():
        errors.append("The term is empty.")
    if not normalized:
        errors.append("The explanation is empty.")
        return errors
    if (
        _IMPERATIVE_EN.search(normalized)
        or _IMPERATIVE_RU.search(normalized)
        or _IMPERATIVE_KK.search(normalized)
    ):
        errors.append(
            "The explanation is a task/learning objective. Rewrite it as a declarative "
            "explanation of the concept."
        )
    if _META_PHRASES.search(normalized):
        errors.append("The explanation contains meta/learning-objective language.")
    if len(words) < min_words:
        errors.append(f"The explanation is too short ({len(words)} words; minimum {min_words}).")
    if len(words) > max_words:
        errors.append(f"The explanation is too long ({len(words)} words; maximum {max_words}).")
    if term and normalized.casefold().strip(" .") == term.casefold().strip(" ."):
        errors.append("The explanation merely repeats the term.")
    return errors


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^\w]+", " ", normalize_text(text).casefold()).strip()


def evidence_in_text(evidence: str, text: str) -> bool:
    """Check whether a quote is present in the source (normalized whitespace)."""
    quote = _normalize_for_match(evidence)
    if len(quote) < 12:
        return False
    return quote in _normalize_for_match(text)


def find_evidence(
    term: str,
    page_texts: dict[int, str],
    pages: list[int],
    *,
    max_chars: int = 220,
) -> str:
    """Find a source sentence that mentions the term, for evidence fallback."""
    target = term.casefold().strip()
    if not target:
        return ""
    candidate_pages = [page_texts[page] for page in pages if page in page_texts] or list(
        page_texts.values()
    )
    for text in candidate_pages:
        for sentence in _SENTENCE_SPLIT.split(text):
            cleaned = _WS.sub(" ", sentence).strip()
            if 20 <= len(cleaned) <= max_chars and target in cleaned.casefold():
                return cleaned
    return ""


def grounding_score(
    explanation: str,
    page_texts: dict[int, str],
    pages: list[int],
) -> tuple[float, list[str]]:
    """Return content-word overlap with the cited pages and the overlap words."""
    words = content_words(explanation)
    if not words:
        return 0.0, []
    source = " ".join(page_texts[page] for page in pages if page in page_texts) or " ".join(
        page_texts.values()
    )
    source_words = set(content_words(source))
    if not source_words:
        return 1.0, []
    overlap = [word for word in set(words) if word in source_words]
    return len(overlap) / len(set(words)), overlap


def _letter_ratio(text: str, predicate) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for char in letters if predicate(char)) / len(letters)


def has_target_script(text: str, language: str) -> bool:
    """Return True when text contains the requested language's writing system."""
    code = language.split("-")[0].lower()
    if not text.strip():
        return False
    if code in _CYRILLIC_LANGS:
        return _letter_ratio(text, lambda char: "\u0400" <= char <= "\u04ff") >= 0.25
    if code == "zh":
        return _letter_ratio(text, lambda char: "\u4e00" <= char <= "\u9fff") >= 0.15
    if code == "ja":
        return (
            _letter_ratio(
                text,
                lambda char: "\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff",
            )
            >= 0.15
        )
    if code == "ko":
        return _letter_ratio(text, lambda char: "\uac00" <= char <= "\ud7af") >= 0.15
    if code == "ar":
        return _letter_ratio(text, lambda char: "\u0600" <= char <= "\u06ff") >= 0.15
    return True


def language_style_errors(text: str, output_language: str) -> list[str]:
    """Flag an explanation that was not written in the requested script."""
    code = output_language.split("-")[0].lower()
    hint = _LANG_SCRIPT_HINTS.get(code)
    if not hint:
        return []
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 12:
        return []
    if not has_target_script(text, code):
        return [
            f"The explanation is not in the requested output language ({code}); "
            f"write it in {hint}."
        ]
    return []


def first_source_sentence(
    page_texts: dict[int, str],
    pages: list[int],
    *,
    max_chars: int = 220,
) -> str:
    """Pick a source-language sentence for translation-mode evidence fallback."""
    candidates = [page_texts[page] for page in pages if page in page_texts] or list(
        page_texts.values()
    )
    for text in candidates:
        for sentence in _SENTENCE_SPLIT.split(text):
            cleaned = _WS.sub(" ", sentence).strip()
            if 24 <= len(cleaned) <= max_chars:
                return cleaned
    for text in candidates:
        cleaned = _WS.sub(" ", text).strip()
        if cleaned:
            return cleaned[:max_chars]
    return ""


def concept_grounding_errors(
    concept: ConceptCard,
    page_texts: dict[int, str],
    *,
    min_overlap: float = 0.2,
    check_overlap: bool = True,
) -> list[str]:
    """Check that a concept's explanation is supported by its cited pages.

    When the output language differs from the document language, lexical overlap
    is not meaningful (translated words will not match the source). In that mode
    the citation/evidence quote is the grounding anchor and overlap is skipped.
    """
    errors: list[str] = []
    source = " ".join(page_texts[page] for page in concept.source_pages if page in page_texts)
    if not source:
        return errors
    if concept.evidence and evidence_in_text(concept.evidence, source):
        return errors
    if not check_overlap:
        return errors
    score, _ = grounding_score(concept.explanation, page_texts, concept.source_pages)
    if score < min_overlap:
        errors.append(
            "The explanation is not sufficiently grounded in the cited pages "
            f"(content-word overlap {score:.0%}; minimum {min_overlap:.0%})."
        )
    return errors


def _term_key(term: str) -> str:
    key = re.sub(r"[^\w]+", " ", term.casefold()).strip()
    if len(key) > 4 and key.endswith("s") and not key.endswith("ss"):
        key = key[:-1]
    return key


def _explanation_key(explanation: str) -> str:
    return re.sub(r"[^\w]+", " ", explanation.casefold()).strip()[:160]


def _clamp_pages(pages: list[int], page_count: int) -> list[int]:
    cleaned: list[int] = []
    for value in pages:
        try:
            page = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= page <= page_count:
            cleaned.append(page)
    return sorted(set(cleaned))


def merge_concepts(
    raw_concepts: list[dict],
    *,
    page_count: int,
    max_concepts: int = 120,
) -> MergedConcepts:
    """Normalize and globally deduplicate concept cards.

    Glossary/reference cards win over prose cards for the same term; otherwise
    the longer explanation is kept. Pages are unioned.
    """
    merged: dict[str, ConceptCard] = {}
    by_explanation: dict[str, str] = {}
    warnings: list[str] = []
    for raw in raw_concepts:
        term = normalize_term(str(raw.get("term", "")))
        explanation = normalize_explanation(str(raw.get("explanation", "")))
        if not term or not explanation:
            continue
        term_key = _term_key(term)
        if _SCAFFOLD_TERM.match(term):
            warnings.append(f"Dropped scaffold concept '{term}'.")
            continue
        if not term_key or term_key in _GENERIC_TERMS:
            warnings.append(f"Dropped generic concept '{term}'.")
            continue
        pages = _clamp_pages(raw.get("source_pages") or [], page_count)
        if not pages:
            continue
        card = ConceptCard(
            id="",
            term=term,
            explanation=explanation,
            evidence=normalize_text(str(raw.get("evidence", "")))[:260],
            source_pages=pages,
            source_section=str(raw.get("source_section", ""))[:160],
            section_kind=raw.get("section_kind", "content"),
        )
        explanation_key = _explanation_key(explanation)
        existing_key = term_key if term_key in merged else by_explanation.get(explanation_key)
        existing = merged.get(existing_key) if existing_key else None
        if existing is None:
            merged[term_key] = card
            by_explanation[explanation_key] = term_key
            continue
        existing.source_pages = sorted(set(existing.source_pages) | set(card.source_pages))
        if card.section_kind == "reference" and existing.section_kind != "reference":
            existing.explanation = card.explanation
            existing.evidence = card.evidence
            existing.section_kind = card.section_kind
            existing.source_section = card.source_section
        elif len(card.explanation) > len(existing.explanation) + 20:
            existing.explanation = card.explanation
            existing.evidence = card.evidence
        if len(card.term.split()) < len(existing.term.split()):
            existing.term = card.term
        warnings.append(f"Merged duplicate concept '{existing.term}'.")

    concepts = list(merged.values())

    # Second pass: merge near-duplicate concepts such as "Attention",
    # "Attention mechanism" and "Attention as a mathematical mechanism" when
    # their grounded explanations substantially overlap.
    deduped: list[ConceptCard] = []
    for card in concepts:
        card_terms = set(content_words(card.term))
        card_expl = set(content_words(card.explanation))
        match: ConceptCard | None = None
        for existing in deduped:
            shared_terms = card_terms & set(content_words(existing.term))
            existing_expl = set(content_words(existing.explanation))
            union = card_expl | existing_expl
            similarity = len(card_expl & existing_expl) / len(union) if union else 0.0
            if (shared_terms and similarity >= 0.5) or similarity >= 0.8:
                match = existing
                break
        if match is None:
            deduped.append(card)
            continue
        match.source_pages = sorted(set(match.source_pages) | set(card.source_pages))
        if card.section_kind == "reference" and match.section_kind != "reference":
            match.explanation = card.explanation
            match.evidence = card.evidence
            match.section_kind = card.section_kind
        elif len(card.explanation) > len(match.explanation) + 20:
            match.explanation = card.explanation
            match.evidence = card.evidence
        if len(card.term.split()) < len(match.term.split()):
            match.term = card.term
        warnings.append(f"Merged similar concept '{card.term}' into '{match.term}'.")
    concepts = deduped

    if len(concepts) > max_concepts:
        warnings.append(
            f"Concept inventory truncated from {len(concepts)} to {max_concepts}."
        )
        concepts = concepts[:max_concepts]
    for index, concept in enumerate(concepts, start=1):
        concept.id = f"c{index}"
    return MergedConcepts(concepts=concepts, warnings=warnings)
