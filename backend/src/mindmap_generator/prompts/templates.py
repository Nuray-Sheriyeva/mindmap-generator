"""Prompt templates for the concept-first mind map pipeline.

Pipeline: extract concept cards → cluster concept IDs → assemble visible leaves.
Prompts are deliberately separate from graph nodes so they can be reviewed,
versioned and evaluated.
"""

from __future__ import annotations

import json

from ..models import ClusterPlan, ConceptCard

PROMPT_VERSION = "2025-10-concept-map-v2"

GROUNDING_RULES = """\
GROUNDING RULES (mandatory):
- Use ONLY the supplied document text. Never add outside knowledge or invented facts.
- Every concept must be traceable to the supplied text and page numbers.
- Evidence must be an exact quote from the text (not a paraphrase).
- If the text does not actually explain an idea, do not create a concept for it.
"""

CONCEPT_RULES = """\
CONCEPT RULES:
- A learning objective is NOT a concept. Sentences such as "Explain what an LLM is...",
  "Describe...", "Distinguish...", "Identify..." describe a goal, not content. Skip them.
- Never create concepts from headings such as "Learning Objectives", "Activities",
  "Knowledge Check", "Suggested Answers", "Glossary", "How to use this lesson".
- A glossary is evidence, not a category.
- Explanations are declarative statements of fact, not instructions and not meta commentary
  ("this section explains", "the document says", "students will").
"""

LANGUAGE_RULES = """\
LANGUAGE RULES:
- Write every term, explanation, category label and subgroup label in the requested
  OUTPUT LANGUAGE, even when the source document is in another language.
- The evidence field is the exception: copy evidence verbatim from the source document
  and NEVER translate it. It must remain in the source language.
- Keep widely used technical names/abbreviations when translating them would be misleading.
"""

LEAF_STYLE_RULES = """\
LEAF STYLE RULES:
- Term: 1-5 words, a concept/topic present in the text, in the OUTPUT LANGUAGE.
- Explanation: 1-2 declarative sentences, roughly 8-28 words, in the OUTPUT LANGUAGE,
  grounded in the source.
- Evidence: a verbatim quote (max 220 characters) in the SOURCE LANGUAGE from the
  supplied pages. Never translate the evidence.
- Never write a task or learning objective as an explanation.
  Bad: "Explain what a large language model is in plain language."
  Good: "A large language model is an AI system trained on large data
  to process and generate language."
"""


def _objectives_block(objectives: list[str] | None) -> str:
    if not objectives:
        return "- (none supplied)"
    return "\n".join(f"- {objective}" for objective in objectives[:20])


# ---------------------------------------------------------------------------
# Concept extraction (map step)
# ---------------------------------------------------------------------------
CONCEPT_SYSTEM = f"""\
You are an expert study-map editor extracting grounded concept cards from one
section of a document.

{GROUNDING_RULES}
{CONCEPT_RULES}
{LANGUAGE_RULES}
{LEAF_STYLE_RULES}

Return JSON only, matching the provided schema. Produce 3-8 concept cards that
explain the section's actual ideas, supporting details and terminology. Do not
summarize the section as a whole; extract the individual ideas a learner should
understand. Avoid near-duplicates and generic cards like "Introduction" or
"Overview"."""


def build_concept_prompt(
    *,
    chunk_text: str,
    section_title: str,
    section_kind: str,
    page_numbers: list[int],
    document_title: str,
    language_name: str,
    source_language_name: str,
    objectives: list[str] | None,
) -> tuple[str, str]:
    """Build the system/user prompt for one concept-extraction call."""
    pages = ", ".join(str(page) for page in page_numbers) or "unknown"
    role_note = (
        "This is a GLOSSARY/REFERENCE section. Extract term → definition pairs; "
        "its definitions are authoritative evidence."
        if section_kind == "reference"
        else "This is a CONTENT section. Explain the ideas, not the learning goals."
    )
    user = f"""\
DOCUMENT TITLE: {document_title}
OUTPUT LANGUAGE: {language_name}
SOURCE LANGUAGE: {source_language_name}
SECTION: {section_title}
SECTION ROLE: {section_kind}
PAGES: {pages}
{role_note}

COVERAGE GOALS (do not copy these as concepts; use them only to notice missing ideas):
{_objectives_block(objectives)}

SECTION TEXT:
<<<
{chunk_text}
>>>

Extract 3-8 grounded concept cards from the section text above. Write the term
and explanation in {language_name}; copy evidence verbatim in {source_language_name}.
Use only page numbers from [{pages}]. Return JSON only.
"""
    return CONCEPT_SYSTEM, user


# ---------------------------------------------------------------------------
# Semantic clustering (reduce step)
# ---------------------------------------------------------------------------
CLUSTER_SYSTEM = """\
You are an information architect building a NotebookLM-style study map.

You receive already-written concept cards. You must NOT rewrite their explanations
or invent new concepts. Your only job is to group concept IDs into a small,
meaningful category hierarchy. The upper nodes are pure categories/generalizations;
the leaves are the supplied concept cards.

STRUCTURE RULES:
- 4-8 main categories (fewer only when the inventory has fewer than 12 concepts).
- Category labels and subgroup labels: 1-3 words, general and conceptual, written in
  the requested OUTPUT LANGUAGE. NEVER return English labels when OUTPUT LANGUAGE is
  not English; translate them.
- Category types to localize: core concepts, creation pipeline, common uses,
  capabilities/limitations, prompting techniques, responsible use.
- Bad labels: Learning Objectives, Activities, Knowledge Check, Glossary,
  Suggested Answers, Final Takeaway, Section 3, Introduction.
- Each category gets 1-6 groups. If no subgrouping is needed, return exactly one
  group with an empty label "" and all of that category's concept IDs.
- Use a named subgroup only when it adds meaning (e.g. "Important Limitations"
  inside "Capabilities and Limitations", "Practical Prompt Formula" inside
  "Prompting Techniques").
- A group should contain 1-6 concept IDs. Prefer 2-4.
- Assign EVERY concept ID exactly once. Never repeat an ID, never invent an ID.
- Do not add explanations, summaries or new leaves. Do not merge concepts.
- Categories must generalize their leaves; avoid single-leaf categories.
- root_label: the document's central topic, short and specific.

Return JSON only, matching the provided schema."""


def build_cluster_prompt(
    *,
    document_title: str,
    language_name: str,
    page_count: int,
    concepts: list[ConceptCard],
    objectives: list[str] | None,
    max_branches: int,
) -> tuple[str, str]:
    """Build the clustering prompt from the grounded concept inventory."""
    inventory = "\n".join(
        f"- {concept.id} | {concept.term} | {concept.explanation} "
        f"| pages {', '.join(str(page) for page in concept.source_pages)}"
        for concept in concepts
    )
    user = f"""\
DOCUMENT TITLE: {document_title}
DOCUMENT PAGES: {page_count}
OUTPUT LANGUAGE: {language_name}
MAX MAIN CATEGORIES: {max_branches}

COVERAGE GOALS (context for grouping only — do not turn these into nodes):
{_objectives_block(objectives)}

CONCEPT INVENTORY ({len(concepts)} concepts):
{inventory}

Group every concept ID above into 4-{max_branches} meaningful categories. Return
JSON only. Remember: leaves keep their existing content; you only choose labels
and assign concept IDs.

There are exactly {len(concepts)} concept IDs. Before returning, count the IDs
across all groups: the total must be {len(concepts)}, and every ID must appear
exactly once. Do not filter, summarize, merge or omit concepts. If the inventory
does not fit, add categories (up to {max_branches}) or groups (up to 6).
"""
    return CLUSTER_SYSTEM, user


# ---------------------------------------------------------------------------
# Concept repair
# ---------------------------------------------------------------------------
CONCEPT_REPAIR_SYSTEM = f"""\
You repair invalid concept cards from a study map. You receive the IDs, current
cards, validation errors and source excerpts. Fix only the listed problems.

{GROUNDING_RULES}
{CONCEPT_RULES}
{LANGUAGE_RULES}
{LEAF_STYLE_RULES}

Rules:
- Preserve every concept ID; return all supplied concepts.
- Keep the original term unless it is empty or has the wrong form.
- Rewrite explanations as declarative, source-grounded statements (8-28 words).
- Replace evidence with a verbatim quote from the supplied excerpts.
- Never introduce learning-objective language or outside facts.
Return JSON only, matching the schema."""


def build_concept_repair_prompt(
    *,
    document_title: str,
    language_name: str,
    source_language_name: str,
    invalid_concepts: list[ConceptCard],
    errors_by_id: dict[str, list[str]],
    page_excerpts: str,
) -> tuple[str, str]:
    """Build the targeted concept repair prompt."""
    cards = []
    for concept in invalid_concepts:
        cards.append(
            {
                "id": concept.id,
                "term": concept.term,
                "explanation": concept.explanation,
                "evidence": concept.evidence,
                "source_pages": concept.source_pages,
                "errors": errors_by_id.get(concept.id, []),
            }
        )
    user = f"""\
DOCUMENT TITLE: {document_title}
OUTPUT LANGUAGE: {language_name}
SOURCE LANGUAGE: {source_language_name}

INVALID CONCEPTS:
<<<
{json.dumps(cards, ensure_ascii=False, indent=2)}
>>>

SOURCE EXCERPTS:
<<<
{page_excerpts}
>>>

Translate terms and explanations into {language_name}; keep evidence as a
verbatim {source_language_name} quote. Return the corrected concept cards
(same IDs) as JSON.
"""
    return CONCEPT_REPAIR_SYSTEM, user


# ---------------------------------------------------------------------------
# Cluster repair
# ---------------------------------------------------------------------------
CLUSTER_REPAIR_SYSTEM = """\
You repair the category hierarchy of a study map. The concept cards are already
grounded; do not rewrite them. Fix only the validation errors in the cluster plan.

Rules:
- Preserve the concept inventory and IDs.
- Translate all category and subgroup labels into the requested OUTPUT LANGUAGE.
- Do not return English labels when the output language is not English.
- Return 4-8 main categories, each with 1-6 groups.
- Use empty group labels when no subgroup is needed.
- Every concept ID exactly once; never invent IDs.
- No category labels such as Learning Objectives, Activities, Glossary, Suggested
  Answers or Final Takeaway.
- Category labels are short (1-3 words) generalizations.
Return the complete corrected JSON only, matching the schema."""


def build_cluster_repair_prompt(
    *,
    document_title: str,
    language_name: str,
    page_count: int,
    concepts: list[ConceptCard],
    cluster: ClusterPlan,
    errors: list[str],
    objectives: list[str] | None,
    max_branches: int,
) -> tuple[str, str]:
    """Build the targeted cluster repair prompt."""
    inventory = "\n".join(
        f"- {concept.id} | {concept.term} | pages "
        f"{', '.join(str(page) for page in concept.source_pages)}"
        for concept in concepts
    )
    user = f"""\
DOCUMENT TITLE: {document_title}
DOCUMENT PAGES: {page_count}
OUTPUT LANGUAGE: {language_name}
MAX MAIN CATEGORIES: {max_branches}

VALIDATION ERRORS:
{chr(10).join(f"- {error}" for error in errors)}

COVERAGE GOALS (context only):
{_objectives_block(objectives)}

CONCEPT INVENTORY:
{inventory}

CURRENT CLUSTER JSON:
<<<
{json.dumps(cluster.model_dump(), ensure_ascii=False, indent=2)}
>>>

The complete inventory has exactly {len(concepts)} concept IDs. The corrected
cluster must contain {len(concepts)} IDs in total, each exactly once. Return the
complete corrected cluster JSON.
"""
    return CLUSTER_REPAIR_SYSTEM, user


# ---------------------------------------------------------------------------
# Focused label translation
# ---------------------------------------------------------------------------
LABEL_TRANSLATION_SYSTEM = """\
You translate the category and subgroup labels of a study map. You receive a
list of labels and the target language. Translate each label into the target
language. Keep well-known technical abbreviations (for example RAG, LLM, API)
when translating them would be misleading. Do not add, remove or reorder labels.
Return every source label exactly as provided and its translation.
Return JSON only, matching the schema."""


def build_label_translation_prompt(
    *,
    labels: list[str],
    language_name: str,
) -> tuple[str, str]:
    """Build a focused translation prompt that preserves cluster structure."""
    listed = "\n".join(f"- {label}" for label in labels)
    user = f"""\
TARGET LANGUAGE: {language_name}

LABELS TO TRANSLATE:
{listed}

Return one entry per label: the original source string and its translation in
{language_name}. Do not leave a label in English unless it is a technical
abbreviation.
"""
    return LABEL_TRANSLATION_SYSTEM, user
