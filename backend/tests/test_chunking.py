"""Chunking tests: section boundaries, overlap, page refs, long blocks."""

from __future__ import annotations

from mindmap_generator.chunking import chunk_document, estimate_tokens
from mindmap_generator.pdf.types import DocumentSection, PageText


def test_short_section_is_one_chunk() -> None:
    section = DocumentSection(
        title="Intro",
        level=1,
        page_start=1,
        page_end=2,
        text="First page text.\n\nSecond page text.",
        blocks=[
            PageText(page=1, text="First page text."),
            PageText(page=2, text="Second page text."),
        ],
    )
    chunks = chunk_document([section], max_chars=1000, overlap_chars=100)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.id == "chunk-0"
    assert chunk.source_pages == [1, 2]
    assert chunk.section_title == "Intro"
    assert chunk.token_estimate == estimate_tokens(chunk.text)


def test_long_section_splits_with_overlap_and_pages() -> None:
    paragraphs = [
        ("One. " + "alpha " * 65).strip(),
        ("Two. " + "beta " * 65).strip(),
        ("Three. " + "gamma " * 65).strip(),
    ]
    section = DocumentSection(
        title="Long",
        level=1,
        page_start=1,
        page_end=3,
        text="\n\n".join(paragraphs),
        blocks=[PageText(page=index + 1, text=text) for index, text in enumerate(paragraphs)],
    )
    chunks = chunk_document([section], max_chars=500, overlap_chars=80)
    assert len(chunks) >= 3
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert all(chunk.source_pages for chunk in chunks)
    assert all(set(chunk.source_pages) <= {1, 2, 3} for chunk in chunks)
    assert any(chunk.source_pages == [3] for chunk in chunks)
    # Overlap means consecutive chunks share a word from the previous tail.
    assert chunks[0].text[-30:].split()[0] in chunks[1].text


def test_long_single_block_is_split() -> None:
    section = DocumentSection(
        title="Monolith",
        level=1,
        page_start=4,
        page_end=4,
        text="Sentence number one. " * 100,
        blocks=[PageText(page=4, text="Sentence number one. " * 100)],
    )
    chunks = chunk_document([section], max_chars=500, overlap_chars=0)
    assert len(chunks) > 1
    assert all(chunk.source_pages == [4] for chunk in chunks)
    assert all(chunk.token_estimate > 0 for chunk in chunks)


def test_empty_sections_are_skipped() -> None:
    section = DocumentSection(
        title="Empty", level=1, page_start=1, page_end=1, text="", blocks=[]
    )
    assert chunk_document([section], max_chars=500, overlap_chars=0) == []
