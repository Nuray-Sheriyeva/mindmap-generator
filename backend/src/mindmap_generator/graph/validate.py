"""Validation, targeted repair and assembly for the concept-first mind map."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..config import Settings
from ..models import (
    ClusterCategory,
    ClusterGroup,
    ClusterPlan,
    ConceptCard,
    LLMClusterOutput,
    MindMapNode,
)
from ..pdf.clean import clean_label
from .concepts import (
    concept_grounding_errors,
    content_words,
    evidence_in_text,
    find_evidence,
    first_source_sentence,
    has_target_script,
    language_style_errors,
    normalize_explanation,
    normalize_term,
    style_errors,
)

_GROUP_LABELS = ["Overview", "Details", "Examples", "Additional", "Further", "Context"]
_MAX_GROUPS_PER_CATEGORY = 8

_BANNED_CATEGORY = re.compile(
    r"^(?:learning\s+objectives?|lesson\s+objectives?|objectives?|"
    r"activities|activity|exercises?|knowledge\s+check|self[-\s]?check|quiz|"
    r"test|questions?|suggested\s+answers?|answer\s+key|glossary|key\s+terms|"
    r"terminology|how\s+to\s+use.*|final\s+takeaway|metadata|"
    r"document\s+information|цели\s+обучения|задачи\s+урока|задания|"
    r"упражнения|проверка\s+знаний|ответы|глоссарий|как\s+пользоваться|итоги|"
    r"оқу\s+мақсаттары|сабақ\s+мақсаттары|тапсырмалар|жауаптар|глоссарий|"
    r"қалай\s+пайдалану|қорытынды)$",
    re.IGNORECASE,
)


@dataclass
class ValidationOutcome:
    """Result of validating concepts + cluster plan."""

    tree: MindMapNode | None
    concepts: list[ConceptCard]
    concept_errors: dict[str, list[str]] = field(default_factory=dict)
    cluster_errors: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        errors: list[str] = []
        for concept_id, messages in self.concept_errors.items():
            errors.extend(f"{concept_id}: {message}" for message in messages)
        errors.extend(self.cluster_errors)
        return errors

    @property
    def valid(self) -> bool:
        return self.tree is not None and not self.errors


def _category_label(value: str) -> str:
    return clean_label(value, max_words=4, max_chars=60).strip(" .:;,—-")


def _group_label(value: str) -> str:
    return clean_label(value, max_words=3, max_chars=48).strip(" .:;,—-")


def _clean_pages(
    pages: list[int],
    page_texts: dict[int, str],
    term: str,
) -> list[int]:
    valid = sorted({page for page in pages if page in page_texts})
    if valid:
        return valid
    needle = term.casefold().strip()
    found = [
        page for page, text in page_texts.items() if needle and needle in text.casefold()
    ]
    return sorted(found)[:2] or sorted(page_texts)[:1] or [1]


def validate_concepts(
    concepts: list[ConceptCard],
    *,
    page_texts: dict[int, str],
    settings: Settings,
    output_language: str,
    same_language: bool,
    fixes: list[str],
) -> tuple[list[ConceptCard], dict[str, list[str]]]:
    """Normalize concepts and return grounding/style errors keyed by concept ID."""
    errors: dict[str, list[str]] = {}
    for concept in concepts:
        original_term = concept.term
        original_explanation = concept.explanation
        concept.term = normalize_term(concept.term)
        concept.explanation = normalize_explanation(concept.explanation)
        if concept.term != original_term:
            fixes.append(f"Shortened concept term '{original_term}' to '{concept.term}'.")
        if concept.explanation != original_explanation:
            fixes.append(f"Normalized explanation for '{concept.term}'.")

        pages = _clean_pages(concept.source_pages, page_texts, concept.term)
        if pages != concept.source_pages:
            fixes.append(f"Adjusted source pages for '{concept.term}'.")
        concept.source_pages = pages

        source_text = " ".join(page_texts[page] for page in pages if page in page_texts)
        if not concept.evidence or not evidence_in_text(concept.evidence, source_text):
            if same_language:
                fallback = find_evidence(concept.term, page_texts, pages)
            else:
                # The explanation/term are translated; keep a source-language
                # quote for traceability instead of comparing translated words.
                fallback = first_source_sentence(page_texts, pages)
            if fallback:
                concept.evidence = fallback
                fixes.append(f"Recovered source-language evidence for '{concept.term}'.")

        messages = style_errors(
            concept.term,
            concept.explanation,
            min_words=settings.min_leaf_words,
            max_words=settings.max_leaf_words,
        )
        messages.extend(language_style_errors(concept.explanation, output_language))
        messages.extend(
            concept_grounding_errors(
                concept,
                page_texts,
                min_overlap=settings.min_grounding_overlap,
                check_overlap=same_language,
            )
        )
        if messages:
            errors[concept.id] = messages
    return concepts, errors


def _parse_cluster(raw: object) -> ClusterPlan:
    if isinstance(raw, ClusterPlan):
        return raw
    if isinstance(raw, LLMClusterOutput):
        return ClusterPlan.model_validate(raw.model_dump())
    return ClusterPlan.model_validate(raw)


def _concept_count(category: ClusterCategory) -> int:
    return sum(len(group.concept_ids) for group in category.groups)


def _concept_words(concept: ConceptCard) -> set[str]:
    return set(content_words(f"{concept.term} {concept.explanation}"))


def _category_words(category: ClusterCategory, by_id: dict[str, ConceptCard]) -> set[str]:
    words = set(content_words(category.label))
    for group in category.groups:
        words.update(content_words(group.label))
        for concept_id in group.concept_ids:
            concept = by_id.get(concept_id)
            if concept is not None:
                words.update(_concept_words(concept))
    return words


def _split_group(
    group: ClusterGroup,
    max_children: int,
    fixes: list[str],
) -> list[ClusterGroup]:
    if len(group.concept_ids) <= max_children:
        return [group]
    parts = [
        group.concept_ids[index : index + max_children]
        for index in range(0, len(group.concept_ids), max_children)
    ]
    fixed: list[ClusterGroup] = []
    for index, part in enumerate(parts):
        label = group.label
        if index > 0:
            label = _group_label(f"{label} {index + 1}") if label else ""
        fixed.append(ClusterGroup(label=label, concept_ids=part))
    fixes.append(
        f"Split subgroup '{group.label or 'unnamed'}' into {len(parts)} groups "
        f"of at most {max_children}."
    )
    return fixed


def _normalize_groups(category: ClusterCategory, max_children: int, fixes: list[str]) -> None:
    groups: list[ClusterGroup] = []
    for group in category.groups:
        groups.extend(_split_group(group, max_children, fixes))
    if len(groups) > _MAX_GROUPS_PER_CATEGORY:
        ids = [concept_id for group in groups for concept_id in group.concept_ids]
        groups = []
        for index in range(0, len(ids), max_children):
            part = ids[index : index + max_children]
            label = _GROUP_LABELS[len(groups) % len(_GROUP_LABELS)]
            groups.append(ClusterGroup(label=label, concept_ids=part))
        fixes.append(
            f"Regrouped '{category.label}' from an oversized group list into "
            f"{len(groups)} groups."
        )
    if len(groups) > 1:
        seen: set[str] = set()
        for index, group in enumerate(groups):
            label = group.label
            if not label:
                label = _GROUP_LABELS[index % len(_GROUP_LABELS)]
            base = label
            suffix = 2
            while label.casefold() in seen:
                label = _group_label(f"{base} {suffix}")
                suffix += 1
            seen.add(label.casefold())
            group.label = label
    elif groups:
        groups[0].label = _group_label(groups[0].label)
    category.groups = groups


def sanitize_cluster(
    concepts: list[ConceptCard],
    plan: ClusterPlan,
    *,
    max_branches: int,
    max_children: int,
    fixes: list[str],
) -> ClusterPlan:
    """Deterministically repair structural cluster problems.

    This prevents an otherwise good LLM mapping from failing because it left a
    few concept IDs out, used too many subgroups, or put too many leaves in one
    subgroup. Semantic concept content is never changed here; only grouping is
    normalized.
    """
    plan = plan.model_copy(deep=True)
    by_id = {concept.id: concept for concept in concepts}
    assigned: set[str] = set()
    categories: list[ClusterCategory] = []

    # 1. Keep known IDs, drop duplicates/unknown IDs, split wide groups.
    for raw_category in plan.categories:
        category = raw_category.model_copy(deep=True)
        category.label = _category_label(category.label)
        groups: list[ClusterGroup] = []
        for raw_group in category.groups:
            label = _group_label(raw_group.label)
            ids: list[str] = []
            for concept_id in raw_group.concept_ids:
                if concept_id not in by_id:
                    fixes.append(
                        f"Dropped unknown concept id '{concept_id}' from '{category.label}'."
                    )
                    continue
                if concept_id in assigned:
                    fixes.append(
                        f"Dropped duplicate concept id '{concept_id}' from '{category.label}'."
                    )
                    continue
                assigned.add(concept_id)
                ids.append(concept_id)
            if not ids:
                continue
            groups.extend(
                _split_group(
                    ClusterGroup(label=label, concept_ids=ids),
                    max_children,
                    fixes,
                )
            )
        category.groups = groups
        if category.groups:
            categories.append(category)

    # 2. Assign concepts the LLM forgot to place, using content overlap.
    for concept in concepts:
        if concept.id in assigned:
            continue
        if not categories:
            category = ClusterCategory(label="Related Concepts", groups=[])
            categories.append(category)
        concept_words = _concept_words(concept)
        ranked = sorted(
            categories,
            key=lambda cat: (
                -len(concept_words & _category_words(cat, by_id)),
                _concept_count(cat),
            ),
        )
        category = ranked[0]
        target: ClusterGroup | None = None
        target_score = -1
        for group in category.groups:
            if len(group.concept_ids) >= max_children:
                continue
            group_words = set(content_words(group.label))
            for concept_id in group.concept_ids:
                existing = by_id.get(concept_id)
                if existing is not None:
                    group_words.update(_concept_words(existing))
            score = len(concept_words & group_words)
            if score > target_score:
                target = group
                target_score = score
        if target is None:
            target = ClusterGroup(label="Additional Concepts", concept_ids=[])
            category.groups.append(target)
        target.concept_ids.append(concept.id)
        assigned.add(concept.id)
        fixes.append(f"Assigned unplaced concept '{concept.term}' to '{category.label}'.")

    # 3. Normalize labels and split oversized groups.
    seen_categories: set[str] = set()
    for category in categories:
        if not category.label or _BANNED_CATEGORY.match(category.label):
            fallback = "Related Concepts"
            if category.groups:
                fallback = _category_label(category.groups[0].label) or fallback
            fixes.append(f"Renamed category '{category.label or 'unnamed'}' to '{fallback}'.")
            category.label = fallback
        base = category.label
        suffix = 2
        while category.label.casefold() in seen_categories:
            category.label = _category_label(f"{base} {suffix}")
            suffix += 1
        seen_categories.add(category.label.casefold())
        _normalize_groups(category, max_children, fixes)

    # 3b. Merge single-concept categories into the closest larger category.
    if len(categories) > 1:
        changed = True
        while changed and len(categories) > 1:
            changed = False
            for victim in list(categories):
                if _concept_count(victim) >= 2:
                    continue
                hosts = [category for category in categories if category is not victim]
                if not hosts:
                    break
                victim_words = _category_words(victim, by_id)
                host = max(
                    hosts,
                    key=lambda category: len(victim_words & _category_words(category, by_id)),
                )
                for group in victim.groups:
                    group.label = _group_label(victim.label) or group.label
                    host.groups.append(group)
                categories.remove(victim)
                _normalize_groups(host, max_children, fixes)
                fixes.append(
                    f"Merged single-concept category '{victim.label}' into '{host.label}'."
                )
                changed = True
                break

    # 4. Keep the category count within the requested maximum by merging the
    # smallest categories into the largest one.
    while len(categories) > max_branches:
        victim = min(categories, key=_concept_count)
        hosts = [category for category in categories if category is not victim]
        if not hosts:
            break
        host = max(hosts, key=_concept_count)
        for group in victim.groups:
            group.label = _group_label(victim.label) or group.label
            host.groups.append(group)
        categories.remove(victim)
        _normalize_groups(host, max_children, fixes)
        fixes.append(f"Merged category '{victim.label}' into '{host.label}'.")

    # 5. Drop categories that no longer have concepts.
    categories = [category for category in categories if _concept_count(category) > 0]
    plan.categories = categories
    return plan


def validate_cluster(
    concepts: list[ConceptCard],
    cluster: ClusterPlan,
    *,
    max_branches: int,
    max_children: int,
    min_leaves: int,
    output_language: str,
    fixes: list[str],
) -> list[str]:
    """Validate category structure and concept assignment."""
    errors: list[str] = []
    concept_ids = {concept.id for concept in concepts}
    if not cluster.categories:
        return ["The cluster plan has no categories."]

    min_categories = 3 if len(concepts) >= 12 else 2
    max_categories = max(2, min(max_branches, 8))
    if not min_categories <= len(cluster.categories) <= max_categories:
        errors.append(
            f"Expected {min_categories}-{max_categories} main categories, "
            f"got {len(cluster.categories)}."
        )

    category_labels: list[str] = []
    assigned: dict[str, int] = {}
    leaf_total = 0
    label_samples: list[str] = []
    for category in cluster.categories:
        label = _category_label(category.label)
        if not label:
            errors.append("A category has an empty label.")
        elif _BANNED_CATEGORY.match(label):
            errors.append(
                f"Category '{label}' is document scaffolding and cannot be a branch."
            )
        if label:
            if label.casefold() in {existing.casefold() for existing in category_labels}:
                errors.append(f"Duplicate category label '{label}'.")
            category_labels.append(label)
            label_samples.append(label)
        category.label = label

        if not category.groups:
            errors.append(f"Category '{label}' has no groups.")
            continue
        if len(category.groups) > _MAX_GROUPS_PER_CATEGORY:
            errors.append(
                f"Category '{label}' has more than {_MAX_GROUPS_PER_CATEGORY} groups."
            )
        group_labels: set[str] = set()
        category_concepts = 0
        for group in category.groups:
            group.label = _group_label(group.label)
            if group.label:
                key = group.label.casefold()
                if key in group_labels:
                    errors.append(f"Duplicate subgroup '{group.label}' in '{label}'.")
                group_labels.add(key)
                label_samples.append(group.label)
                if _BANNED_CATEGORY.match(group.label):
                    errors.append(
                        f"Subgroup '{group.label}' is document scaffolding."
                    )
            if len(category.groups) > 1 and not group.label:
                errors.append(f"Category '{label}' needs names for all its subgroups.")
            if not group.concept_ids:
                errors.append(f"Subgroup '{group.label or label}' is empty.")
            if len(group.concept_ids) > max_children:
                errors.append(
                    f"Subgroup '{group.label or label}' has more than {max_children} leaves."
                )
            for concept_id in group.concept_ids:
                if concept_id not in concept_ids:
                    errors.append(f"Unknown concept id '{concept_id}' in '{label}'.")
                    continue
                assigned[concept_id] = assigned.get(concept_id, 0) + 1
                category_concepts += 1
                leaf_total += 1
        if category_concepts < 2:
            errors.append(f"Category '{label}' must generalize at least 2 concepts.")

    duplicates = sorted(concept_id for concept_id, count in assigned.items() if count > 1)
    if duplicates:
        errors.append(f"Concept ids assigned more than once: {', '.join(duplicates)}.")
    missing = sorted(concept_ids - set(assigned))
    if missing:
        errors.append(f"Unassigned concept ids: {', '.join(missing)}.")
    if leaf_total < min_leaves:
        errors.append(
            f"The map has {leaf_total} leaves; expected at least {min_leaves} for this document."
        )
    if label_samples:
        localized = sum(
            1 for label in label_samples if has_target_script(label, output_language)
        )
        if localized < max(1, len(label_samples) // 2):
            errors.append(
                "Category/group labels are not in the requested output language "
                f"({output_language}); translate every label."
            )
    if not errors:
        fixes.append(
            f"Clustered {len(concepts)} concepts into {len(cluster.categories)} categories."
        )
    return errors


def _leaf_node(concept: ConceptCard) -> MindMapNode:
    return MindMapNode(
        kind="leaf",
        label=concept.term,
        explanation=concept.explanation,
        source_pages=concept.source_pages,
        children=[],
    )


def assemble_tree(
    concepts: list[ConceptCard],
    cluster: ClusterPlan,
    *,
    document_title: str,
    max_depth: int = 3,
) -> MindMapNode:
    """Build the final root/branch/leaf tree from validated IDs and labels."""
    by_id = {concept.id: concept for concept in concepts}
    root_label = clean_label(
        cluster.root_label or document_title,
        max_words=8,
        max_chars=90,
    ) or clean_label(document_title, max_words=8, max_chars=90) or "Mind map"
    root = MindMapNode(kind="root", label=root_label, children=[], source_pages=[])

    for category in cluster.categories:
        category_node = MindMapNode(
            kind="branch",
            label=_category_label(category.label),
            children=[],
            source_pages=[],
        )
        if max_depth <= 2:
            for group in category.groups:
                category_node.children.extend(
                    _leaf_node(by_id[concept_id])
                    for concept_id in group.concept_ids
                    if concept_id in by_id
                )
        elif len(category.groups) == 1 and not category.groups[0].label:
            category_node.children = [
                _leaf_node(by_id[concept_id])
                for concept_id in category.groups[0].concept_ids
                if concept_id in by_id
            ]
        else:
            for group in category.groups:
                leaves = [
                    _leaf_node(by_id[concept_id])
                    for concept_id in group.concept_ids
                    if concept_id in by_id
                ]
                label = _group_label(group.label)
                if not label or label.casefold() == category_node.label.casefold():
                    category_node.children.extend(leaves)
                else:
                    category_node.children.append(
                        MindMapNode(
                            kind="branch",
                            label=label,
                            children=leaves,
                            source_pages=[],
                        )
                    )
        if category_node.children:
            root.children.append(category_node)
    return root


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


def count_nodes(root: MindMapNode) -> int:
    """Count all nodes in a tree."""
    return len(flatten_tree(root))


def count_leaves(root: MindMapNode) -> int:
    """Count leaf nodes."""
    return sum(1 for node in flatten_tree(root) if node.kind == "leaf")


def count_branches(root: MindMapNode) -> int:
    """Count branch nodes, excluding the root."""
    return sum(1 for node in flatten_tree(root) if node.kind == "branch")


def tree_depth(root: MindMapNode) -> int:
    """Maximum depth below the root (root itself = 0)."""
    if not root.children:
        return 0
    return 1 + max(tree_depth(child) for child in root.children)


def validate_map(
    concepts: list[ConceptCard],
    cluster: ClusterPlan | dict | LLMClusterOutput,
    *,
    document_title: str,
    page_texts: dict[int, str],
    settings: Settings,
    max_branches: int,
    min_leaves: int,
    max_depth: int = 3,
    output_language: str = "en",
    document_language: str = "en",
) -> ValidationOutcome:
    """Validate concepts and clustering, then assemble the tree when valid.

    Returns separate error buckets so the graph can repair concepts first and
    categories second.
    """
    fixes: list[str] = []
    same_language = (
        output_language.split("-")[0].casefold()
        == document_language.split("-")[0].casefold()
    )
    concepts, concept_errors = validate_concepts(
        concepts,
        page_texts=page_texts,
        settings=settings,
        output_language=output_language,
        same_language=same_language,
        fixes=fixes,
    )
    try:
        plan = _parse_cluster(cluster)
    except (ValidationError, TypeError, ValueError) as exc:
        return ValidationOutcome(
            tree=None,
            concepts=concepts,
            concept_errors=concept_errors,
            cluster_errors=[f"The cluster response is not a valid hierarchy: {exc}"],
            fixes=fixes,
        )

    plan = sanitize_cluster(
        concepts,
        plan,
        max_branches=max_branches,
        max_children=settings.max_children,
        fixes=fixes,
    )
    cluster_errors = validate_cluster(
        concepts,
        plan,
        max_branches=max_branches,
        max_children=settings.max_children,
        min_leaves=min_leaves,
        output_language=output_language,
        fixes=fixes,
    )
    if concept_errors or cluster_errors:
        return ValidationOutcome(
            tree=None,
            concepts=concepts,
            concept_errors=concept_errors,
            cluster_errors=cluster_errors,
            fixes=fixes,
        )

    tree = assemble_tree(
        concepts,
        plan,
        document_title=document_title,
        max_depth=max_depth,
    )
    return ValidationOutcome(tree=tree, concepts=concepts, fixes=fixes)


def page_excerpts(
    concepts: list[ConceptCard],
    page_texts: dict[int, str],
    *,
    max_chars: int = 7000,
) -> str:
    """Concatenate cited page text for targeted concept repair."""
    pages: set[int] = set()
    for concept in concepts:
        pages.update(concept.source_pages)
    chunks: list[str] = []
    used = 0
    for page in sorted(pages):
        text = page_texts.get(page, "").strip()
        if not text:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = f"--- page {page} ---\n{text[:remaining]}"
        chunks.append(excerpt)
        used += len(excerpt)
    return "\n\n".join(chunks)
