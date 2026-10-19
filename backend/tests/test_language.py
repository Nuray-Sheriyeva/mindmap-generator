"""Language detection tests (Latin, Cyrillic incl. Kazakh, CJK)."""

from __future__ import annotations

from mindmap_generator.languages import (
    detect_language,
    language_name,
    resolve_output_language,
)


def test_detects_english() -> None:
    text = "The document explains how photosynthesis works and why it matters for life."
    assert detect_language(text) == "en"


def test_detects_russian() -> None:
    text = (
        "Это документ о фотосинтезе. В нём описаны основные процессы. "
        "Для растений это важно, и данные подтверждают выводы."
    )
    assert detect_language(text) == "ru"


def test_detects_kazakh_letters() -> None:
    text = (
        "Бұл құжат фотосинтез туралы. Әрбір өсімдік үшін маңызды. "
        "Қазақ тіліндегі мәтін осы жерде сипатталады."
    )
    assert detect_language(text) == "kk"


def test_detects_cjk() -> None:
    assert detect_language("東京で会議が行われました。これは日本語の文章です。") == "ja"
    assert detect_language("这是一个中文文档，描述了光合作用的过程。") == "zh"


def test_language_helpers() -> None:
    assert language_name("kk") == "Kazakh"
    assert language_name("xx") == "xx"
    assert resolve_output_language("ru", None) == "ru"
    assert resolve_output_language("ru", "en") == "en"
