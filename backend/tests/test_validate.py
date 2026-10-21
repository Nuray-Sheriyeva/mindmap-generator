"""Validation, grounding, dedupe and tree-assembly tests for schema v2."""

from __future__ import annotations

import pytest
from conftest import DEFAULT_CONCEPTS, make_cluster

from mindmap_generator.config import Settings
from mindmap_generator.graph.concepts import (
    evidence_in_text,
    merge_concepts,
    normalize_explanation,
    style_errors,
)
from mindmap_generator.graph.validate import (
    assemble_tree,
    assign_stable_ids,
    count_branches,
    count_leaves,
    count_nodes,
    flatten_tree,
    tree_depth,
    validate_map,
)
from mindmap_generator.models import ClusterPlan, ConceptCard
from mindmap_generator.pdf.classify import page_text_map
from mindmap_generator.pdf.extract import parse_pdf_document

SETTINGS = Settings(max_pages=50, min_leaf_words=5, max_leaf_words=32)


@pytest.fixture(scope="module")
def page_texts(sample_pdf_bytes: bytes) -> dict[int, str]:
    parsed = parse_pdf_document(sample_pdf_bytes, "sample.pdf", SETTINGS)
    return page_text_map(parsed.sections)


def concepts() -> list[ConceptCard]:
    return merge_concepts(DEFAULT_CONCEPTS, page_count=3).concepts


def test_valid_map_assembles_branch_and_leaf_nodes(page_texts) -> None:
    cards = concepts()
    cluster = make_cluster([card.id for card in cards])
    outcome = validate_map(
        cards,
        cluster,
        document_title="Photosynthesis",
        page_texts=page_texts,
        settings=SETTINGS,
        max_branches=7,
        min_leaves=6,
    )
    assert outcome.valid, outcome.errors
    assert outcome.tree is not None
    tree = assign_stable_ids(outcome.tree)
    assert tree.kind == "root"
    assert tree.explanation is None
    assert len(tree.children) == 4
    assert count_leaves(tree) == len(cards)
    assert count_branches(tree) == 4
    assert count_nodes(tree) == 1 + 4 + len(cards)
    assert tree_depth(tree) == 2
    assert all(leaf.explanation for leaf in flatten_tree(tree) if leaf.kind == "leaf")
    assert all(not node.explanation for node in flatten_tree(tree) if node.kind != "leaf")
    ids = [node.id for node in flatten_tree(tree)]
    assert len(ids) == len(set(ids))


def test_learning_objective_explanation_triggers_concept_repair(page_texts) -> None:
    cards = concepts()
    cards[0].explanation = "Explain what photosynthesis is in plain language."
    cluster = make_cluster([card.id for card in cards])
    outcome = validate_map(
        cards,
        cluster,
        document_title="Photosynthesis",
        page_texts=page_texts,
        settings=SETTINGS,
        max_branches=7,
        min_leaves=6,
    )
    assert not outcome.valid
    assert cards[0].id in outcome.concept_errors
    assert any("task/learning objective" in error for error in outcome.concept_errors[cards[0].id])


def test_metric_style_and_meta_language() -> None:
    assert style_errors("Photosynthesis", "Explain what photosynthesis is."), "imperative"
    assert style_errors("Photosynthesis", "This section explains photosynthesis."), "meta"
    assert style_errors("Photosynthesis", "It is a process."), "too short"
    assert style_errors("Photosynthesis", "Photosynthesis")
    assert style_errors(
        "Photosynthesis",
        "Photosynthesis converts light energy into chemical energy inside chloroplasts.",
    ) == []


def test_explanation_normalization_and_evidence() -> None:
    assert normalize_explanation("Definition: A cell is the basic unit of life.") == (
        "A cell is the basic unit of life."
    )
    assert evidence_in_text(
        "Photosynthesis converts light energy into chemical energy.",
        "Photosynthesis converts light energy into chemical energy. It occurs in chloroplasts.",
    )
    assert not evidence_in_text("A fabricated sentence about cells.", "Cells contain a nucleus.")


def test_similar_concepts_with_overlapping_explanations_are_merged() -> None:
    raw = [
        {
            "term": "Attention",
            "explanation": "Attention is a mechanism that weighs relationships between tokens in context.",
            "evidence": "Attention is a mechanism that weighs relationships between tokens in context.",
            "source_pages": [2],
        },
        {
            "term": "Attention mechanism",
            "explanation": "Attention is a mechanism that helps weigh relationships between tokens in context.",
            "evidence": "Attention is a mechanism that helps weigh relationships between tokens in context.",
            "source_pages": [3],
        },
        {
            "term": "Chloroplasts",
            "explanation": "Chloroplasts are organelles where photosynthesis takes place.",
            "evidence": "Chloroplasts are organelles where photosynthesis takes place.",
            "source_pages": [1],
        },
    ]
    merged = merge_concepts(raw, page_count=3)
    assert len(merged.concepts) == 2
    attention = next(card for card in merged.concepts if "attention" in card.term.casefold())
    assert attention.source_pages == [2, 3]
    assert any("Merged similar concept" in warning for warning in merged.warnings)


def test_generic_terms_and_duplicate_explanations_are_merged() -> None:
    raw = [
        {
            "term": "Model",
            "explanation": "A model is a mathematical system.",
            "evidence": "A model is a mathematical system.",
            "source_pages": [1],
        },
        {
            "term": "Tokens",
            "explanation": "Tokens are units of text processed by a model.",
            "evidence": "Tokens are units of text processed by a model.",
            "source_pages": [1],
        },
        {
            "term": "Token",
            "explanation": "Tokens are units of text processed by a model.",
            "evidence": "Tokens are units of text processed by a model.",
            "source_pages": [1],
        },
        {
            "term": "Parameters",
            "explanation": "Parameters are learned numerical values inside a model.",
            "evidence": "Parameters are learned numerical values inside a model.",
            "source_pages": [1],
        },
        {
            "term": "Learning Objectives",
            "explanation": "Explain what parameters are in plain language.",
            "evidence": "Parameters are learned numerical values inside a model.",
            "source_pages": [1],
        },
    ]
    merged = merge_concepts(raw, page_count=3)
    terms = [card.term.casefold() for card in merged.concepts]
    assert "model" not in terms
    assert len(merged.concepts) == 2
    assert any("Dropped generic" in warning for warning in merged.warnings)
    assert any("Dropped scaffold" in warning for warning in merged.warnings)
    assert any("Merged duplicate" in warning for warning in merged.warnings)


def test_cluster_scaffold_label_is_renamed(page_texts) -> None:
    cards = concepts()
    ids = [card.id for card in cards]
    cluster = make_cluster(ids)
    cluster["categories"][0]["label"] = "Learning Objectives"
    outcome = validate_map(
        cards,
        cluster,
        document_title="Photosynthesis",
        page_texts=page_texts,
        settings=SETTINGS,
        max_branches=7,
        min_leaves=6,
    )
    assert outcome.valid, outcome.errors
    assert outcome.tree is not None
    labels = [branch.label for branch in outcome.tree.children]
    assert "Learning Objectives" not in labels
    assert any("Renamed category" in fix for fix in outcome.fixes)


def test_missing_duplicate_and_unknown_ids_are_auto_repaired(page_texts) -> None:
    cards = concepts()
    ids = [card.id for card in cards]
    cluster = make_cluster(ids)
    cluster["categories"][0]["groups"][0]["concept_ids"].append(ids[0])
    cluster["categories"][1]["groups"][0]["concept_ids"].append("c999")
    cluster["categories"][0]["groups"][0]["concept_ids"].pop(1)
    outcome = validate_map(
        cards,
        cluster,
        document_title="Photosynthesis",
        page_texts=page_texts,
        settings=SETTINGS,
        max_branches=7,
        min_leaves=6,
    )
    assert outcome.valid, outcome.errors
    assert outcome.tree is not None
    joined = " ".join(outcome.fixes)
    assert "Dropped duplicate concept id" in joined
    assert "Dropped unknown concept id" in joined
    assert "Assigned unplaced concept" in joined
    leaves = [node for node in flatten_tree(outcome.tree) if node.kind == "leaf"]
    assert len(leaves) == len(cards)
    assert len({leaf.label for leaf in leaves}) == len(leaves)


def test_sanitize_splits_wide_groups_and_keeps_all_concepts() -> None:
    from mindmap_generator.graph.validate import sanitize_cluster

    cards = concepts()
    plan = ClusterPlan.model_validate(
        {
            "root_label": "Photosynthesis",
            "categories": [
                {
                    "label": "Training and Mechanisms",
                    "groups": [
                        {"label": "", "concept_ids": [card.id for card in cards]},
                    ],
                }
            ],
        }
    )
    fixes: list[str] = []
    sanitized = sanitize_cluster(
        cards,
        plan,
        max_branches=7,
        max_children=6,
        fixes=fixes,
    )
    assert all(
        len(group.concept_ids) <= 6
        for category in sanitized.categories
        for group in category.groups
    )
    assigned = [
        concept_id
        for category in sanitized.categories
        for group in category.groups
        for concept_id in group.concept_ids
    ]
    assert sorted(assigned) == sorted(card.id for card in cards)
    assert any("Split subgroup" in fix for fix in fixes)


def test_assembler_flattens_subgroups_for_max_depth_two() -> None:
    cards = concepts()
    by_ids = [card.id for card in cards]
    plan = ClusterPlan.model_validate(
        {
            "root_label": "Photosynthesis",
            "categories": [
                {
                    "label": "Core Concepts",
                    "groups": [
                        {"label": "Overview", "concept_ids": by_ids[:3]},
                        {"label": "Details", "concept_ids": by_ids[3:6]},
                    ],
                },
                {
                    "label": "Applications",
                    "groups": [
                        {"label": "Overview", "concept_ids": by_ids[6:8]},
                        {"label": "Details", "concept_ids": by_ids[8:10]},
                    ],
                },
            ],
        }
    )
    tree = assign_stable_ids(
        assemble_tree(cards, plan, document_title="Photosynthesis", max_depth=2)
    )
    assert tree_depth(tree) == 2
    assert all(
        child.kind == "leaf" for branch in tree.children for child in branch.children
    )
    assert count_leaves(tree) == 10


def test_final_node_schema_rejects_branch_explanations_and_leaf_children() -> None:
    from mindmap_generator.models import MindMapNode

    with pytest.raises(ValueError):
        MindMapNode(kind="branch", label="Core", explanation="not allowed")
    with pytest.raises(ValueError):
        MindMapNode(
            kind="leaf",
            label="Tokens",
            explanation="Tokens are units of text.",
            children=[MindMapNode(kind="branch", label="Nested")],
        )


def test_tree_metrics() -> None:
    cards = concepts()
    tree = assemble_tree(
        cards,
        ClusterPlan.model_validate(make_cluster([card.id for card in cards])),
        document_title="Photosynthesis",
    )
    assign_stable_ids(tree)
    assert count_nodes(tree) == 15
    assert count_leaves(tree) == 10
    assert count_branches(tree) == 4
    assert tree_depth(tree) == 2
