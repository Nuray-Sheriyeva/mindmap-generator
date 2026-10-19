"""Structural validation, repair and ID assignment for generated mind maps."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..models import GenerationOptions, LLMLevel0Node, MindMapNode
from ..pdf.clean import clean_label, normalize_text, truncate_at_sentence

_MAX_SUMMARY_CHARS = 320
_MAX_LABEL_WORDS = 6
_MAX_PAGES_PER_NODE = 12


@dataclass
class ValidationOutcome:
    """Result of validating one LLM draft."""

    tree: MindMapNode | None
    errors: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)


def _has_cycle(value: Any, seen: set[int] | None = None) -> bool:
    """Defensive cycle check for JSON-derived structures."""
    if seen is None:
        seen = set()
    if isinstance(value, dict):
        if id(value) in seen:
            return True
        seen.add(id(value))
        return any(_has_cycle(child, seen) for child in value.values())
    if isinstance(value, list):
        if id(value) in seen:
            return True
        seen.add(id(value))
        return any(_has_cycle(child, seen) for child in value)
    return False


def _strip_leaf_children(value: Any, depth: int = 0) -> None:
    """Remove the optional ``children`` key from level-3 leaves.

    The structured-output schema models the fourth tier as a leaf, but some
    providers still emit ``"children": []``. Normalising here avoids a
    spurious schema failure (and any deeper content is truncated anyway).
    """
    if not isinstance(value, dict):
        return
    if depth >= 3:
        value.pop("children", None)
        return
    children = value.get("children")
    if isinstance(children, list):
        for child in children:
            _strip_leaf_children(child, depth + 1)


def _clean_pages(
    raw_pages: Any,
    *,
    parent_pages: list[int],
    page_count: int,
    label: str,
    fixes: list[str],
) -> list[int]:
    pages: list[int] = []
    if isinstance(raw_pages, list):
        for value in raw_pages:
            try:
                pages.append(int(value))
            except (TypeError, ValueError):
                continue
    valid = [page for page in pages if 1 <= page <= page_count]
    cleaned = sorted(set(valid))[:_MAX_PAGES_PER_NODE]
    if not cleaned:
        cleaned = list(parent_pages) or [1]
        fixes.append(f"Inherited missing source pages for '{label}'.")
    elif len(valid) != len(pages) or len(valid) != len(set(valid)):
        fixes.append(f"Clamped/removed invalid page references for '{label}'.")
    return cleaned


def _convert_node(
    raw: dict[str, Any],
    *,
    depth: int,
    options: GenerationOptions,
    page_count: int,
    parent_pages: list[int],
    fixes: list[str],
) -> MindMapNode | None:
    label = clean_label(str(raw.get("label", "")), max_words=_MAX_LABEL_WORDS)
    if not label:
        fixes.append("Dropped a node with an empty label.")
        return None
    if len(str(raw.get("label", "")).split()) > _MAX_LABEL_WORDS:
        fixes.append(f"Shortened overlong label to '{label}'.")

    summary = truncate_at_sentence(normalize_text(str(raw.get("summary", ""))), _MAX_SUMMARY_CHARS)
    if len(str(raw.get("summary", ""))) > _MAX_SUMMARY_CHARS:
        fixes.append(f"Trimmed a long summary on '{label}'.")

    source_pages = _clean_pages(
        raw.get("source_pages", []),
        parent_pages=parent_pages,
        page_count=page_count,
        label=label,
        fixes=fixes,
    )

    children: list[MindMapNode] = []
    raw_children = raw.get("children") or []
    if depth < options.max_depth and isinstance(raw_children, list):
        cap = options.max_branches if depth == 0 else options.max_children
        if len(raw_children) > cap:
            fixes.append(
                f"Truncated '{label}' from {len(raw_children)} to {cap} children."
            )
        seen_labels: set[str] = set()
        for child_raw in raw_children[:cap]:
            if not isinstance(child_raw, dict):
                continue
            child = _convert_node(
                child_raw,
                depth=depth + 1,
                options=options,
                page_count=page_count,
                parent_pages=source_pages,
                fixes=fixes,
            )
            if child is None:
                continue
            key = re.sub(r"\s+", " ", child.label.casefold())
            if key in seen_labels:
                fixes.append(f"Dropped duplicate sibling '{child.label}'.")
                continue
            seen_labels.add(key)
            children.append(child)

    return MindMapNode(
        label=label,
        summary=summary,
        source_pages=source_pages,
        children=children,
    )


def validate_hierarchy(
    draft: dict[str, Any],
    *,
    options: GenerationOptions,
    page_count: int,
    document_title: str,
) -> ValidationOutcome:
    """Validate an LLM draft and repair structural problems.

    Repairs: empty labels, duplicate siblings, over-deep branches, over-wide
    branches, overlong labels/summaries, and invalid page references. Hard
    errors (which trigger an LLM repair call) are malformed structure, a missing
    root, too few main branches, or branches with no supporting children.
    """
    errors: list[str] = []
    fixes: list[str] = []

    if not isinstance(draft, dict) or not draft:
        return ValidationOutcome(None, ["The response is empty or not a JSON object."], fixes)
    if _has_cycle(draft):
        return ValidationOutcome(None, ["The tree contains a cycle."], fixes)

    normalised = copy.deepcopy(draft)
    _strip_leaf_children(normalised)
    try:
        validated = LLMLevel0Node.model_validate(normalised)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:4]
        )
        return ValidationOutcome(
            None,
            [f"The JSON structure does not match the required schema ({details})."],
            fixes,
        )

    raw = validated.model_dump()
    if not str(raw.get("label", "")).strip():
        raw["label"] = document_title or "Document"
        fixes.append("Replaced an empty root label with the document title.")

    root = _convert_node(
        raw,
        depth=0,
        options=options,
        page_count=page_count,
        parent_pages=[1],
        fixes=fixes,
    )
    if root is None:
        return ValidationOutcome(None, ["The mind map has no usable root node."], fixes)

    if len(root.children) < 2:
        errors.append("The root must have at least 2 main branches.")
    elif len(root.children) > options.max_branches:
        root.children = root.children[: options.max_branches]
        fixes.append(f"Truncated the root to {options.max_branches} main branches.")

    if len(root.children) >= 2:
        childless = sum(1 for branch in root.children if not branch.children)
        if childless > len(root.children) / 2:
            errors.append(
                "Most main branches have no children; add supporting sub-topics from the document."
            )

    return ValidationOutcome(root, errors, fixes)


def count_nodes(root: MindMapNode) -> int:
    """Count all nodes in a tree."""
    return 1 + sum(count_nodes(child) for child in root.children)


def tree_depth(root: MindMapNode) -> int:
    """Maximum depth below the root (root itself = 0)."""
    if not root.children:
        return 0
    return 1 + max(tree_depth(child) for child in root.children)


def assign_stable_ids(root: MindMapNode) -> MindMapNode:
    """Assign deterministic path IDs (``root``, ``root.1``, ``root.1.2``)."""

    def walk(node: MindMapNode, path: str) -> None:
        node.id = path
        for index, child in enumerate(node.children, start=1):
            walk(child, f"{path}.{index}")

    walk(root, "root")
    return root


def flatten_tree(root: MindMapNode) -> list[MindMapNode]:
    """Depth-first flatten, used by exports and tests."""
    nodes = [root]
    for child in root.children:
        nodes.extend(flatten_tree(child))
    return nodes
