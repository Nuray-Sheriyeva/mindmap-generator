"""Schema validation, structural repair and ID assignment tests."""

from __future__ import annotations

import copy

from conftest import make_tree

from mindmap_generator.graph.validate import (
    assign_stable_ids,
    count_nodes,
    flatten_tree,
    tree_depth,
    validate_hierarchy,
)
from mindmap_generator.models import GenerationOptions

OPTIONS = GenerationOptions(max_depth=2, max_branches=3, max_children=2)
WIDE_OPTIONS = GenerationOptions(max_depth=2, max_branches=4, max_children=2)


def _validate(draft, options=OPTIONS, page_count=3, title="Photosynthesis"):
    return validate_hierarchy(
        draft, options=options, page_count=page_count, document_title=title
    )


def test_valid_tree_passes_unchanged() -> None:
    outcome = _validate(make_tree(branches=3, children=2, depth=2))
    assert outcome.errors == []
    assert outcome.tree is not None
    assert len(outcome.tree.children) == 3
    assert tree_depth(outcome.tree) == 2


def test_repairs_duplicates_width_depth_pages_and_labels() -> None:
    draft = make_tree(branches=3, children=2, depth=3)
    # Overlong label and summary -> trimmed.
    draft["children"][0]["label"] = "An extremely long branch label with many extra words here"
    draft["children"][0]["summary"] = "Long summary. " * 60
    # Duplicate a whole branch (same label) -> deduped.
    draft["children"].insert(1, copy.deepcopy(draft["children"][0]))
    # Over-wide branch -> truncated to max_children.
    extra = copy.deepcopy(draft["children"][1]["children"][0])
    extra["label"] = "Extra child"
    draft["children"][1]["children"].append(extra)
    # Empty child label -> dropped.
    draft["children"][2]["children"][0]["label"] = "   "
    # Out-of-range pages -> clamped/inherited.
    draft["children"][2]["source_pages"] = [0, 99]

    outcome = _validate(draft, options=WIDE_OPTIONS)
    assert outcome.tree is not None
    assert outcome.errors == []
    root = outcome.tree
    assert len(root.children) == 3
    assert tree_depth(root) <= OPTIONS.max_depth
    assert len(root.children[1].children) <= OPTIONS.max_children
    labels = [child.label.casefold() for child in root.children]
    assert len(labels) == len(set(labels))
    assert len(root.children[0].label.split()) <= 6
    assert len(root.children[0].summary) <= 321
    assert all(1 <= page <= 3 for node in flatten_tree(root) for page in node.source_pages)
    assert outcome.fixes


def test_empty_root_label_falls_back_to_document_title() -> None:
    draft = make_tree(branches=2, children=2, depth=2)
    draft["label"] = ""
    outcome = _validate(draft, title="My Document")
    assert outcome.tree is not None
    assert outcome.tree.label == "My Document"
    assert any("root label" in fix for fix in outcome.fixes)


def test_too_few_branches_is_a_hard_error() -> None:
    outcome = _validate(make_tree(branches=1, children=2, depth=2))
    assert outcome.tree is not None
    assert any("at least 2 main branches" in error for error in outcome.errors)


def test_childless_branches_trigger_repair_error() -> None:
    draft = make_tree(branches=4, children=0, depth=2)
    outcome = _validate(draft)
    assert outcome.tree is not None
    assert any("no children" in error for error in outcome.errors)


def test_malformed_structure_is_rejected() -> None:
    outcome = _validate({"something": "else"})
    assert outcome.tree is None
    assert outcome.errors


def test_cycle_is_rejected() -> None:
    draft: dict = {"label": "Root", "summary": "", "source_pages": [1], "children": []}
    draft["children"].append(draft)  # type: ignore[arg-type]
    outcome = _validate(draft)
    assert outcome.tree is None
    assert "cycle" in outcome.errors[0].lower()


def test_stable_ids_and_metrics() -> None:
    outcome = _validate(make_tree(branches=2, children=2, depth=3))
    assert outcome.tree is not None
    tree = assign_stable_ids(outcome.tree)
    assert tree.id == "root"
    assert tree.children[0].id == "root.1"
    assert tree.children[0].children[0].id == "root.1.1"
    ids = [node.id for node in flatten_tree(tree)]
    assert len(ids) == len(set(ids))
    assert count_nodes(tree) == len(ids)
    assert tree_depth(tree) <= OPTIONS.max_depth
