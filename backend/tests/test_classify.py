"""Section classification: objectives, activities, glossary and metadata."""

from __future__ import annotations

from mindmap_generator.config import Settings
from mindmap_generator.pdf.classify import (
    classify_section,
    classify_sections,
    extract_objectives,
    page_text_map,
)
from mindmap_generator.pdf.extract import parse_pdf_document
from mindmap_generator.pdf.types import DocumentSection, PageText


def _section(title: str, text: str, *, level: int = 1, page: int = 1) -> DocumentSection:
    return DocumentSection(
        title=title,
        text=text,
        level=level,
        page_start=page,
        page_end=page,
        blocks=[PageText(page=page, text=text)],
    )


def test_classifies_scaffold_objectives_activities_and_reference() -> None:
    assert classify_section(_section("Learning Objectives", "Explain what a cell is.")) == (
        "objectives"
    )
    assert classify_section(_section("Activities", "Activity A ...")) == "activities"
    assert classify_section(_section("Knowledge Check", "1. What is a cell?")) == "activities"
    assert classify_section(_section("Suggested Answers", "1. A cell is ...")) == "activities"
    assert classify_section(_section("Glossary", "Term Meaning ...")) == "reference"
    assert classify_section(_section("Term Meaning Attention", "A mechanism ...")) == "reference"
    assert classify_section(_section("Level", "Beginner")) == "scaffold"
    assert classify_section(_section("Format", "Reading and examples")) == "scaffold"
    assert classify_section(_section("Designed for", "Students and curious learners")) == "scaffold"
    assert classify_section(
        _section("What is a cell?", "A cell is the basic unit of life.")
    ) == "content"


def test_glossary_range_is_propagated() -> None:
    sections = [
        _section("Cells", "Cells are the basic units of life.", level=1),
        _section("Glossary", "Term Meaning", level=1),
        _section("Membrane", "A boundary that controls what enters the cell.", level=3),
        _section("Nucleus", "A structure that stores genetic information.", level=3),
        _section("Final takeaway", "Cells are the building blocks of life.", level=1),
    ]
    classified, objectives = classify_sections(sections)
    kinds = [section.kind for section in classified]
    assert kinds[1] == "reference"
    assert kinds[2] == "reference"
    assert kinds[3] == "reference"
    assert kinds[4] == "scaffold"
    assert objectives == []


def test_extracts_objective_bullets_as_checklist() -> None:
    sections, _ = classify_sections(
        [
            _section(
                "Learning Objectives",
                "By the end of this lesson, you should be able to: "
                "• Explain what an LLM is in plain language. "
                "• Describe tokens and next-token prediction. "
                "• Distinguish pretraining from instruction tuning.",
            )
        ]
    )
    objectives = extract_objectives(sections)
    assert any("Explain what an LLM is" in objective for objective in objectives)
    assert any("Describe tokens" in objective for objective in objectives)
    assert any("Distinguish pretraining" in objective for objective in objectives)


def test_objectives_pdf_integration(objectives_pdf_bytes: bytes) -> None:
    parsed = parse_pdf_document(objectives_pdf_bytes, "objectives.pdf", Settings(max_pages=10))
    classified, objectives = classify_sections(parsed.sections)
    content_titles = [
        section.title for section in classified if section.kind in {"content", "reference"}
    ]
    assert "Learning Objectives" not in content_titles
    assert any("Cell Structure" in title for title in content_titles)
    assert len(objectives) >= 2
    pages = page_text_map(classified)
    assert 1 in pages and 2 in pages
