/** Pure tree helpers: visibility, lookup, colors and page formatting. */

import type { MindMapNode } from '../types/mindmap';

export const BRANCH_COLORS = [
  '#2563eb',
  '#0d9488',
  '#d97706',
  '#c026d3',
  '#e11d48',
  '#7c3aed',
  '#0891b2',
  '#65a30d',
] as const;

export const ROOT_COLOR = '#334155';

export interface VisibleNode {
  node: MindMapNode;
  depth: number;
  branchIndex: number;
}

export function collectVisible(
  root: MindMapNode,
  collapsed: ReadonlySet<string>,
): VisibleNode[] {
  const result: VisibleNode[] = [];
  const walk = (node: MindMapNode, depth: number, branchIndex: number) => {
    result.push({ node, depth, branchIndex });
    if (depth === 0) {
      node.children.forEach((child, index) => {
        walk(child, 1, index);
      });
      return;
    }
    if (collapsed.has(node.id)) return;
    node.children.forEach((child) => walk(child, depth + 1, branchIndex));
  };
  walk(root, 0, -1);
  return result;
}

export function findNode(root: MindMapNode, id: string | null): MindMapNode | null {
  if (!id) return null;
  if (root.id === id) return root;
  for (const child of root.children) {
    const match = findNode(child, id);
    if (match) return match;
  }
  return null;
}

/** Labels from the root to the node (inclusive). */
export function findPathLabels(root: MindMapNode, id: string | null): string[] {
  if (!id) return [];
  const path: string[] = [];
  const walk = (node: MindMapNode, trail: string[]): boolean => {
    const next = [...trail, node.label];
    if (node.id === id) {
      path.push(...next);
      return true;
    }
    return node.children.some((child) => walk(child, next));
  };
  walk(root, []);
  return path;
}

export function countTreeNodes(root: MindMapNode): number {
  return 1 + root.children.reduce((total, child) => total + countTreeNodes(child), 0);
}

export function treeDepth(root: MindMapNode): number {
  if (root.children.length === 0) return 0;
  return 1 + Math.max(...root.children.map(treeDepth));
}

export function collectIdsWithChildren(root: MindMapNode): string[] {
  const ids: string[] = [];
  const walk = (node: MindMapNode) => {
    if (node.children.length > 0) ids.push(node.id);
    node.children.forEach(walk);
  };
  walk(root);
  return ids;
}

export function colorForBranch(branchIndex: number): string {
  if (branchIndex < 0) return ROOT_COLOR;
  return BRANCH_COLORS[branchIndex % BRANCH_COLORS.length];
}

/** Collapse page numbers into compact ranges: [1,2,4] → "1–2, 4". */
export function formatPages(pages: ReadonlyArray<number>): string {
  const values = [...new Set(pages.filter((page) => Number.isFinite(page) && page > 0))].sort(
    (a, b) => a - b,
  );
  if (values.length === 0) return '';
  const ranges: string[] = [];
  let start = values[0];
  let previous = values[0];
  for (const page of values.slice(1)) {
    if (page === previous + 1) {
      previous = page;
      continue;
    }
    ranges.push(start === previous ? String(start) : `${start}–${previous}`);
    start = page;
    previous = page;
  }
  ranges.push(start === previous ? String(start) : `${start}–${previous}`);
  return ranges.join(', ');
}

export function toggleCollapsed(
  collapsed: ReadonlySet<string>,
  id: string,
): Set<string> {
  const next = new Set(collapsed);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
