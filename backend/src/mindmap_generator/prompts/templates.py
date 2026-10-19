"""Prompt templates for the mind map pipeline.

Prompts are kept out of graph nodes so they can be reviewed, versioned and
tested independently. Every prompt enforces grounding in the supplied document,
source-page citations, short labels and output-language mirroring.
"""

from __future__ import annotations

from ..models import ChunkSummary
from ..pdf.types import DocumentSection

PROMPT_VERSION = "2024-10-v1"

GROUNDING_RULES = """\
GROUNDING RULES (mandatory):
- Use ONLY information explicitly present in the supplied document text.
- Never add outside knowledge, interpretations, or invented facts.
- Every node's source_pages must come from the page numbers provided; use the
  page(s) where the supporting text appears. Never invent page numbers.
- If the document does not support a point, omit it.
"""

STYLE_RULES = """\
STYLE RULES:
- Labels are concise noun phrases: at most 6 words, no trailing period.
- Summaries are 1-2 short sentences copied/paraphrased from the document.
- Write in the requested output language.
- Keep all proper nouns, technical terms and numbers faithful to the source.
"""


def outline_block(sections: list[DocumentSection]) -> str:
    """Render a compact section outline for hierarchy prompts."""
    lines = []
    for section in sections:
        pages = (
            f"{section.page_start}"
            if section.page_start == section.page_end
            else f"{section.page_start}-{section.page_end}"
        )
        lines.append(f"- L{section.level} | pages {pages} | {section.title}")
    return "\n".join(lines) if lines else "- (no headings detected; treat as one section)"


# ---------------------------------------------------------------------------
# Map step
# ---------------------------------------------------------------------------
SUMMARIZE_SYSTEM = f"""\
You are an expert document analyst building the evidence base for a mind map.
Extract only the key concepts, short summaries and important terms from the
single document chunk provided.

{GROUNDING_RULES}
{STYLE_RULES}
- Produce 2-6 key concepts (each with a short label and a 1-sentence summary).
- Produce up to 10 key terms exactly as they appear in the text.
- The chunk summary is at most 2 sentences.
Return JSON only, matching the provided schema."""


def build_summarize_prompt(
    *,
    chunk_text: str,
    section_title: str,
    page_numbers: list[int],
    document_title: str,
    language_name: str,
) -> tuple[str, str]:
    """Build the system/user prompt for one map-step call."""
    pages = ", ".join(str(page) for page in page_numbers) or "unknown"
    user = f"""\
DOCUMENT TITLE: {document_title}
OUTPUT LANGUAGE: {language_name}
SECTION: {section_title}
PAGES: {pages}

CHUNK TEXT:
<<<
{chunk_text}
>>>

Extract the chunk's summary, key concepts and key terms. Use only the text above.
Set source_pages to a subset of [{pages}].
"""
    return SUMMARIZE_SYSTEM, user


# ---------------------------------------------------------------------------
# Reduce step
# ---------------------------------------------------------------------------
HIERARCHY_SYSTEM = """\
You are an expert information architect. Build ONE hierarchical mind map from
the supplied document material.

STRUCTURE:
- One central root topic that captures the document's main subject.
- Main branches: between {min_branches} and {max_branches} branches, covering
  distinct major themes.
- Each branch has 2-6 children; children may have 2-6 children of their own.
- Maximum depth below the root: {max_depth} levels. Deeper levels are optional.
- No duplicate labels among siblings, no empty nodes.

{grounding}
{style}
- Page citations must be plausible for the document (1 to {page_count}).
Return JSON only, matching the provided schema."""


def build_hierarchy_prompt(
    *,
    document_title: str,
    language_name: str,
    page_count: int,
    max_depth: int,
    min_branches: int,
    max_branches: int,
    sections: list[DocumentSection],
    chunk_summaries: list[ChunkSummary] | None,
    document_text: str | None,
) -> tuple[str, str]:
    """Build the reduce/single-call prompt.

    Short documents pass ``document_text``; long documents pass grounded
    ``chunk_summaries`` from the map step.
    """
    system = HIERARCHY_SYSTEM.format(
        min_branches=min_branches,
        max_branches=max_branches,
        max_depth=max_depth,
        page_count=page_count,
        grounding=GROUNDING_RULES,
        style=STYLE_RULES,
    )
    parts = [
        f"DOCUMENT TITLE: {document_title}",
        f"OUTPUT LANGUAGE: {language_name}",
        f"DOCUMENT PAGES: {page_count}",
        f"MAX DEPTH BELOW ROOT: {max_depth}",
        f"MAIN BRANCHES: {min_branches}-{max_branches}",
        "",
        "DOCUMENT OUTLINE:",
        outline_block(sections),
        "",
    ]
    if chunk_summaries:
        parts.append("CHUNK SUMMARIES (grounded evidence):")
        for summary in chunk_summaries:
            pages = ", ".join(str(page) for page in summary.source_pages)
            concepts = "; ".join(
                f"{concept.label} — {concept.summary} "
                f"(pages {', '.join(str(p) for p in concept.source_pages)})"
                for concept in summary.key_concepts
            )
            parts.append(
                f"### {summary.section_title} (pages {pages})\n"
                f"Summary: {summary.summary}\n"
                f"Concepts: {concepts}\n"
                f"Key terms: {', '.join(summary.key_terms)}"
            )
    elif document_text:
        parts.append("DOCUMENT TEXT:")
        parts.append("<<<")
        parts.append(document_text)
        parts.append(">>>")
    parts.append(
        "\nBuild the single best mind map. Every node must be directly supported by "
        "the material above and must carry source_pages."
    )
    return system, "\n".join(parts)


# ---------------------------------------------------------------------------
# Repair step
# ---------------------------------------------------------------------------
REPAIR_SYSTEM = f"""\
You repair an invalid hierarchical mind map. You receive the draft JSON and a
list of validation errors. Fix ONLY the listed problems while preserving valid,
source-grounded content.

{GROUNDING_RULES}
{STYLE_RULES}
- Keep the root topic.
- Ensure 4-8 main branches when the document supports it (minimum 2).
- Remove duplicates and empty labels; shorten overlarge labels.
- Stay within the depth/branch limits given by the validation errors.
Return the complete corrected JSON only, matching the provided schema."""


def build_repair_prompt(
    *,
    draft_json: str,
    errors: list[str],
    document_title: str,
    language_name: str,
    max_depth: int,
    max_branches: int,
    page_count: int,
) -> tuple[str, str]:
    """Build a repair prompt containing the validation errors."""
    user = f"""\
DOCUMENT TITLE: {document_title}
OUTPUT LANGUAGE: {language_name}
LIMITS: max depth below root = {max_depth}; max main branches = {max_branches};
pages = 1-{page_count}

VALIDATION ERRORS:
{chr(10).join(f"- {error}" for error in errors)}

DRAFT JSON:
<<<
{draft_json}
>>>

Return the corrected complete mind map JSON.
"""
    return REPAIR_SYSTEM, user
