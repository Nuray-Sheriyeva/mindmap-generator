"""PDF ingestion: text extraction, outline/heading detection and cleaning."""

from __future__ import annotations

import io
import logging
from pathlib import Path

try:  # PyMuPDF >= 1.24 exposes ``pymupdf``; ``fitz`` remains as an alias.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - compatibility with older PyMuPDF
    import fitz  # type: ignore[no-redef]

from pypdf import PdfReader

from ..config import Settings
from ..errors import (
    InvalidPDFError,
    MindMapError,
    NoExtractableTextError,
    PageLimitError,
)
from ..languages import detect_language
from .clean import clean_label, clean_line, join_lines, remove_boilerplate
from .headings import detect_headings
from .types import (
    DocumentSection,
    ExtractionResult,
    OutlineEntry,
    PageText,
    Paragraph,
    ParsedDocument,
    RawLine,
)

logger = logging.getLogger(__name__)

_PDF_HEADER = b"%PDF-"


def looks_like_pdf(data: bytes) -> bool:
    """Check the PDF magic bytes (the header may be within the first 1 KiB)."""
    return _PDF_HEADER in data[:1024]


def _extract_outline(doc: fitz.Document) -> list[OutlineEntry]:
    """Read PDF bookmarks, clamped to the three supported heading levels."""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:  # pragma: no cover - malformed outline
        return []
    entries: list[OutlineEntry] = []
    for level, title, page in toc:
        cleaned = clean_line(str(title or ""))
        if not cleaned or not page or int(page) < 1:
            continue
        entries.append(
            OutlineEntry(title=cleaned, level=max(1, min(int(level), 3)), page=int(page))
        )
    return entries


def _line_from_fitz(line: dict) -> RawLine | None:
    spans = line.get("spans", [])
    parts: list[str] = []
    sizes: list[float] = []
    bold = False
    for span in spans:
        text = span.get("text", "")
        if not text:
            continue
        parts.append(text)
        if text.strip():
            sizes.append(float(span.get("size", 0) or 0))
        font = str(span.get("font", "")).casefold()
        flags = int(span.get("flags", 0) or 0)
        if flags & 16 or any(token in font for token in ("bold", "black", "heavy", "semibold")):
            bold = True
    text = clean_line("".join(parts))
    if not text:
        return None
    bbox = line.get("bbox") or (0, 0, 0, 0)
    return RawLine(
        text=text,
        page=0,  # filled in by caller
        size=max(sizes) if sizes else 0.0,
        bold=bold,
        y=float(bbox[1]),
        height=max(0.0, float(bbox[3]) - float(bbox[1])),
    )


def _extract_with_pymupdf(data: bytes, settings: Settings) -> ExtractionResult:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPDFError(f"Could not open the PDF: {exc}") from exc

    try:
        if doc.needs_pass or doc.is_encrypted:
            raise InvalidPDFError(
                "This PDF is encrypted/password-protected. Remove the password and retry.",
                code="encrypted_pdf",
            )
        page_count = doc.page_count
        if page_count <= 0:
            raise InvalidPDFError("The PDF contains no pages.", code="empty_pdf")
        if page_count > settings.max_pages:
            raise PageLimitError(page_count, settings.max_pages)

        pages: list[list[RawLine]] = []
        warnings: list[str] = []
        for page in doc:
            try:
                page_dict = page.get_text("dict", sort=True)
            except Exception as exc:
                warnings.append(f"Page {page.number + 1} could not be fully parsed: {exc}")
                pages.append([])
                continue
            lines: list[RawLine] = []
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    parsed = _line_from_fitz(line)
                    if parsed is None:
                        continue
                    parsed.page = page.number + 1
                    lines.append(parsed)
            pages.append(lines)

        removed = remove_boilerplate(pages)
        if removed:
            warnings.append(f"Removed {removed} running header/footer/page-number lines.")
        paragraphs = _lines_to_paragraphs(pages)
        outline = _extract_outline(doc)
        metadata_title = None
        try:
            metadata_title = str((doc.metadata or {}).get("title") or "").strip() or None
        except Exception:
            metadata_title = None
        return ExtractionResult(
            pages=pages,
            paragraphs=paragraphs,
            outline=outline,
            metadata_title=metadata_title,
            warnings=warnings,
        )
    finally:
        doc.close()


def _extract_with_pypdf(data: bytes, settings: Settings) -> ExtractionResult:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise InvalidPDFError(f"Could not open the PDF with the fallback parser: {exc}") from exc

    if reader.is_encrypted:
        try:
            if reader.decrypt("") == 0:
                raise InvalidPDFError(
                    "This PDF is encrypted/password-protected. Remove the password and retry.",
                    code="encrypted_pdf",
                )
        except InvalidPDFError:
            raise
        except Exception as exc:
            raise InvalidPDFError(
                "This PDF is encrypted/password-protected.", code="encrypted_pdf"
            ) from exc

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise InvalidPDFError(f"The PDF is corrupt or unreadable: {exc}") from exc
    if page_count <= 0:
        raise InvalidPDFError("The PDF contains no pages.", code="empty_pdf")
    if page_count > settings.max_pages:
        raise PageLimitError(page_count, settings.max_pages)

    pages: list[list[RawLine]] = []
    warnings: list[str] = ["Font metadata unavailable; used the pypdf fallback extractor."]
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"Page {page_number} could not be parsed: {exc}")
            raw = ""
        lines: list[RawLine] = []
        for index, text_line in enumerate(raw.splitlines()):
            text = clean_line(text_line)
            if not text:
                continue
            lines.append(RawLine(text=text, page=page_number, y=float(index * 14)))
        pages.append(lines)

    removed = remove_boilerplate(pages)
    if removed:
        warnings.append(f"Removed {removed} running header/footer/page-number lines.")
    return ExtractionResult(
        pages=pages,
        paragraphs=_lines_to_paragraphs(pages),
        outline=[],
        metadata_title=None,
        warnings=warnings,
    )


def _lines_to_paragraphs(pages: list[list[RawLine]]) -> list[Paragraph]:
    """Merge line runs into visual paragraphs using style and vertical gaps."""

    def flush(lines: list[RawLine], output: list[Paragraph]) -> None:
        if not lines:
            return
        text = join_lines([line.text for line in lines])
        if not text:
            return
        sizes = [line.size for line in lines if line.size > 0]
        output.append(
            Paragraph(
                text=text,
                page=lines[0].page,
                size=max(sizes) if sizes else 0.0,
                bold=sum(1 for line in lines if line.bold) >= max(1, len(lines) // 2),
                y=lines[0].y,
            )
        )

    paragraphs: list[Paragraph] = []
    for lines in pages:
        current: list[RawLine] = []
        for line in lines:
            if not current:
                current = [line]
                continue
            previous = current[-1]
            style_changed = abs(line.size - previous.size) > 0.6 or line.bold != previous.bold
            gap = line.y - (previous.y + max(previous.height, previous.size * 0.9))
            big_gap = gap > max(6.0, previous.size * 1.2)
            if style_changed or big_gap:
                flush(current, paragraphs)
                current = [line]
            else:
                current.append(line)
        flush(current, paragraphs)
    return paragraphs


def _page_blocks(paragraphs: list[Paragraph]) -> list[PageText]:
    blocks: list[PageText] = []
    current_page: int | None = None
    current: list[str] = []
    for paragraph in paragraphs:
        if paragraph.page != current_page:
            if current_page is not None and current:
                blocks.append(PageText(page=current_page, text="\n\n".join(current)))
            current_page = paragraph.page
            current = [paragraph.text]
        else:
            current.append(paragraph.text)
    if current_page is not None and current:
        blocks.append(PageText(page=current_page, text="\n\n".join(current)))
    return blocks


def _make_section(
    title: str,
    level: int,
    paragraphs: list[Paragraph],
    *,
    page_start: int | None = None,
    fallback_title: str = "Document",
) -> DocumentSection:
    cleaned_title = clean_label(title or fallback_title, max_words=12, max_chars=120)
    text = "\n\n".join(paragraph.text for paragraph in paragraphs)
    start = page_start or (paragraphs[0].page if paragraphs else 1)
    end = paragraphs[-1].page if paragraphs else start
    return DocumentSection(
        title=cleaned_title or fallback_title,
        level=max(1, min(level, 3)),
        page_start=start,
        page_end=max(start, end),
        text=text,
        blocks=_page_blocks(paragraphs),
    )


def build_sections(
    paragraphs: list[Paragraph], headings, document_title: str
) -> list[DocumentSection]:
    """Build sections from paragraph ranges delimited by detected headings."""
    if not headings:
        return [_make_section(document_title, 1, paragraphs, fallback_title="Document")]

    sections: list[DocumentSection] = []
    first = headings[0]
    preamble = paragraphs[: first.index]
    if preamble and len(" ".join(p.text for p in preamble)) >= 40:
        sections.append(
            _make_section(document_title, 1, preamble, fallback_title="Document overview")
        )

    for position, heading in enumerate(headings):
        end = headings[position + 1].index if position + 1 < len(headings) else len(paragraphs)
        body = paragraphs[heading.index + 1 : end]
        if not body:
            continue
        section = _make_section(
            heading.title,
            heading.level,
            body,
            page_start=heading.page,
            fallback_title=document_title,
        )
        if section.text.strip():
            sections.append(section)

    if not sections:
        return [_make_section(document_title, 1, paragraphs, fallback_title="Document")]
    return sections


def _document_title(
    filename: str, metadata_title: str | None, headings, sections: list[DocumentSection]
) -> str:
    if metadata_title and metadata_title.casefold() not in {"untitled", "unknown"}:
        return clean_label(metadata_title, max_words=14, max_chars=120)
    if headings:
        return clean_label(headings[0].title, max_words=14, max_chars=120)
    if sections and sections[0].title:
        return sections[0].title
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return clean_label(stem, max_words=14, max_chars=120) or "Document"


def _count_text_chars(sections: list[DocumentSection]) -> int:
    return sum(1 for section in sections for char in section.text if char.isalnum())


def parse_pdf_document(data: bytes, filename: str, settings: Settings) -> ParsedDocument:
    """Parse a PDF into cleaned sections, raising domain errors on bad input.

    Extraction strategy: PyMuPDF first (text + font style + bookmarks), then
    pypdf when PyMuPDF finds no text. Encrypted PDFs and page-limit violations
    are rejected before extraction.
    """
    safe_name = Path(filename or "document.pdf").name
    if not looks_like_pdf(data):
        raise InvalidPDFError("The uploaded file is not a valid PDF (missing %PDF- header).")

    extraction = "pymupdf"
    warnings: list[str] = []
    try:
        result = _extract_with_pymupdf(data, settings)
        warnings.extend(result.warnings)
    except MindMapError:
        raise
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("PyMuPDF extraction failed, falling back to pypdf: %s", exc)
        result = _extract_with_pypdf(data, settings)
        extraction = "pypdf"
        warnings.extend(result.warnings)

    if not result.paragraphs:
        try:
            fallback = _extract_with_pypdf(data, settings)
        except MindMapError:
            raise
        if fallback.paragraphs:
            result = fallback
            extraction = "pypdf"
            warnings = list(dict.fromkeys([*warnings, *fallback.warnings]))

    if not result.paragraphs:
        raise NoExtractableTextError()

    headings, outline_used = detect_headings(result.paragraphs, result.outline)
    title = _document_title(safe_name, result.metadata_title, headings, [])
    sections = build_sections(result.paragraphs, headings, title)

    sections = [section for section in sections if section.text.strip()]
    if not sections:
        raise NoExtractableTextError()
    if _count_text_chars(sections) < settings.min_extractable_chars:
        raise NoExtractableTextError()

    full_text = "\n\n".join(section.text for section in sections)
    language = detect_language(full_text)
    title = _document_title(safe_name, result.metadata_title, headings, sections)

    logger.info(
        "Parsed PDF pages=%d sections=%d chars=%d outline=%s extractor=%s",
        len(result.pages),
        len(sections),
        len(full_text),
        outline_used,
        extraction,
    )
    return ParsedDocument(
        filename=safe_name,
        pages=len(result.pages),
        language=language,
        title=title,
        sections=sections,
        extraction=extraction,
        outline_used=outline_used,
        warnings=warnings,
    )


def inspect_pdf(data: bytes, settings: Settings) -> int:
    """Fast upload-time validation: magic bytes, encryption and page count.

    This deliberately does not extract text; text extraction happens in the
    background job so the upload response stays immediate.
    """
    if not looks_like_pdf(data):
        raise InvalidPDFError("The uploaded file is not a valid PDF (missing %PDF- header).")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPDFError(f"The PDF is corrupt or unreadable: {exc}") from exc
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise InvalidPDFError(
                "This PDF is encrypted/password-protected. Remove the password and retry.",
                code="encrypted_pdf",
            )
        page_count = doc.page_count
        if page_count <= 0:
            raise InvalidPDFError("The PDF contains no pages.", code="empty_pdf")
        if page_count > settings.max_pages:
            raise PageLimitError(page_count, settings.max_pages)
        return page_count
    finally:
        doc.close()
