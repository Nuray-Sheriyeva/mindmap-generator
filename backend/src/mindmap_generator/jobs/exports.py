"""Result exporters: canonical JSON and a human-readable Markdown outline."""

from __future__ import annotations

import json
from typing import Any


def format_pages(pages: list[int]) -> str:
    """Format page numbers compactly (``[1, 2, 4]`` → ``1–2, 4``)."""
    values = sorted({int(page) for page in pages if int(page) > 0})
    if not values:
        return ""
    ranges: list[str] = []
    start = previous = values[0]
    for page in values[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(f"{start}–{previous}" if start != previous else str(start))
        start = previous = page
    ranges.append(f"{start}–{previous}" if start != previous else str(start))
    return ", ".join(ranges)


def export_json(result: dict[str, Any]) -> str:
    """Serialize the canonical result as pretty JSON."""
    return json.dumps(result, ensure_ascii=False, indent=2)


def _render_node(node: dict[str, Any], level: int, lines: list[str]) -> None:
    heading = "#" * min(level, 6)
    lines.append(f"{heading} {node.get('label', 'Untitled')}")
    summary = (node.get("summary") or "").strip()
    if summary:
        lines.append("")
        lines.append(summary)
    pages = format_pages(node.get("source_pages") or [])
    if pages:
        lines.append("")
        lines.append(f"_Source pages: {pages}_")
    lines.append("")
    for child in node.get("children") or []:
        _render_node(child, level + 1, lines)


def export_markdown(result: dict[str, Any]) -> str:
    """Render the result as a Markdown outline with summaries and page refs."""
    document = result.get("document") or {}
    meta = result.get("meta") or {}
    root = result.get("mindmap") or {"label": "Mind map", "children": []}

    lines: list[str] = []
    _render_node(root, 1, lines)

    source = f"> Source: `{document.get('filename', 'document.pdf')}`"
    source += f" · {document.get('pages', '?')} page(s)"
    source += f" · language: {document.get('language', 'unknown')}"
    lines.append(source)
    details = []
    if meta.get("model"):
        details.append(f"model: {meta['model']}")
    if meta.get("generated_at"):
        details.append(f"generated: {meta['generated_at']}")
    if meta.get("node_count") is not None:
        details.append(f"nodes: {meta['node_count']}")
    if details:
        lines.append("> " + " · ".join(details))
    lines.append("")
    return "\n".join(lines)
