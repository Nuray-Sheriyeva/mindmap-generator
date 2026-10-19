"""Data structures shared by the PDF extraction stages."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


@dataclass(slots=True)
class RawLine:
    """A single extracted text line with the style hints needed for heuristics."""

    text: str
    page: int
    size: float = 0.0
    bold: bool = False
    y: float = 0.0
    height: float = 0.0


@dataclass(slots=True)
class Paragraph:
    """A visual paragraph assembled from one or more extracted lines."""

    text: str
    page: int
    size: float
    bold: bool
    y: float = 0.0


@dataclass(slots=True)
class Heading:
    """A detected heading anchored to a global paragraph index."""

    index: int
    title: str
    level: int
    page: int


@dataclass(slots=True)
class OutlineEntry:
    """A PDF bookmark entry."""

    title: str
    level: int
    page: int


class PageText(BaseModel):
    """Text belonging to one page inside a section."""

    page: int
    text: str


class DocumentSection(BaseModel):
    """A logical section of the document.

    ``text`` is the cleaned body (the heading itself is excluded), while
    ``blocks`` retains the page mapping used for precise source-page refs when
    chunking long sections.
    """

    title: str
    level: int = 1
    page_start: int
    page_end: int
    text: str = ""
    blocks: list[PageText] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """Structured representation of an uploaded PDF."""

    filename: str
    pages: int
    language: str
    title: str
    sections: list[DocumentSection]
    extraction: str = "pymupdf"
    outline_used: bool = False
    warnings: list[str] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Return all section bodies joined in reading order."""
        return "\n\n".join(section.text for section in self.sections if section.text.strip())


@dataclass(slots=True)
class ExtractionResult:
    """Intermediate raw extraction result before section building."""

    pages: list[list[RawLine]] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    outline: list[OutlineEntry] = field(default_factory=list)
    metadata_title: str | None = None
    warnings: list[str] = field(default_factory=list)
