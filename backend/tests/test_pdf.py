"""PDF extraction, cleaning and heading detection tests."""

from __future__ import annotations

import pytest

import mindmap_generator.pdf.extract as extract_module
from mindmap_generator.config import Settings
from mindmap_generator.errors import (
    InvalidPDFError,
    NoExtractableTextError,
    PageLimitError,
)
from mindmap_generator.pdf.clean import clean_label, is_page_number, join_lines
from mindmap_generator.pdf.extract import inspect_pdf, parse_pdf_document
from mindmap_generator.pdf.headings import numbering_heading

SETTINGS = Settings(max_pages=50)


def test_extracts_sections_and_pages(sample_pdf_bytes: bytes) -> None:
    parsed = parse_pdf_document(sample_pdf_bytes, "sample.pdf", SETTINGS)

    assert parsed.pages == 3
    assert parsed.title == "Photosynthesis"
    assert parsed.language == "en"
    assert parsed.extraction == "pymupdf"
    assert parsed.outline_used is False

    titles = [section.title for section in parsed.sections]
    assert "Introduction" in titles
    assert "Light Reactions" in titles
    assert "Calvin Cycle" in titles
    assert "Applications" in titles

    introduction = next(s for s in parsed.sections if s.title == "Introduction")
    assert introduction.level == 1
    assert introduction.page_start == 1
    assert "photosynthesis is essential for life on earth" in introduction.text.casefold()

    light = next(s for s in parsed.sections if s.title == "Light Reactions")
    assert light.level == 2
    assert light.page_start == 2
    assert "thylakoid" in light.text


def test_removes_running_headers_footers_and_page_numbers(sample_pdf_bytes: bytes) -> None:
    parsed = parse_pdf_document(sample_pdf_bytes, "sample.pdf", SETTINGS)
    combined = "\n".join(section.text for section in parsed.sections)
    assert "Sample Document" not in combined
    assert "Page 1" not in combined
    assert "Page 2" not in combined
    assert not any(is_page_number(line) for line in combined.splitlines())
    assert any("running header" in warning for warning in parsed.warnings)


def test_fixes_hyphenation_across_lines(sample_pdf_bytes: bytes) -> None:
    parsed = parse_pdf_document(sample_pdf_bytes, "sample.pdf", SETTINGS)
    combined = "\n".join(section.text for section in parsed.sections)
    assert "Photo- synthesis" not in combined
    assert "photosynthesis is essential" in combined.casefold()


def test_outline_has_priority(outline_pdf_bytes: bytes) -> None:
    parsed = parse_pdf_document(outline_pdf_bytes, "outline.pdf", SETTINGS)
    assert parsed.outline_used is True
    titles = [section.title for section in parsed.sections]
    for expected in ("Overview", "Background", "Methods", "Results"):
        assert expected in titles


def test_pypdf_fallback(
    monkeypatch: pytest.MonkeyPatch, sample_pdf_bytes: bytes
) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("simulated PyMuPDF failure")

    monkeypatch.setattr(extract_module, "_extract_with_pymupdf", explode)
    parsed = parse_pdf_document(sample_pdf_bytes, "sample.pdf", SETTINGS)
    assert parsed.extraction == "pypdf"
    assert parsed.sections
    assert parsed.pages == 3


def test_rejects_non_pdf() -> None:
    with pytest.raises(InvalidPDFError) as excinfo:
        inspect_pdf(b"plain text", SETTINGS)
    assert excinfo.value.code == "invalid_pdf"


def test_rejects_encrypted_pdf(encrypted_pdf_bytes: bytes) -> None:
    with pytest.raises(InvalidPDFError) as excinfo:
        inspect_pdf(encrypted_pdf_bytes, SETTINGS)
    assert excinfo.value.code == "encrypted_pdf"


def test_page_limit(sample_pdf_bytes: bytes) -> None:
    with pytest.raises(PageLimitError) as excinfo:
        inspect_pdf(sample_pdf_bytes, Settings(max_pages=1))
    assert excinfo.value.status_code == 422
    assert excinfo.value.details["pages"] == 3


def test_no_extractable_text(blank_pdf_bytes: bytes) -> None:
    with pytest.raises(NoExtractableTextError):
        parse_pdf_document(blank_pdf_bytes, "blank.pdf", SETTINGS)


def test_numbering_patterns() -> None:
    assert numbering_heading("1. Introduction") == ("Introduction", 1)
    assert numbering_heading("2.3 Results") == ("Results", 2)
    assert numbering_heading("2.3.1 Deep dive") == ("Deep dive", 3)
    assert numbering_heading("Chapter 4: Methods") == ("Methods", 1)
    assert numbering_heading("Глава 2. Обзор") == ("Обзор", 1)
    assert numbering_heading("1.5 million people live here") is None
    assert numbering_heading("This is a normal sentence.") is None


def test_clean_helpers() -> None:
    assert join_lines(["Photo-", "synthesis"]) == "Photosynthesis"
    assert join_lines(["фото-", "синтез"]) == "фотосинтез"
    assert is_page_number("12")
    assert is_page_number("Page 3 of 10")
    assert not is_page_number("Chapter 3")
    assert clean_label("  A very long heading with far too many words here  ", max_words=4) == (
        "A very long heading"
    )
