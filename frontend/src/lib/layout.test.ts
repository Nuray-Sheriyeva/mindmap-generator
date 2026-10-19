import { describe, expect, it } from 'vitest';

import { SAMPLE_RESULT } from '../data/sample';
import { buildLayout } from './layout';
import { collectVisible, countTreeNodes, findNode } from './tree';

const root = SAMPLE_RESULT.mindmap;

describe('buildLayout', () => {
  it('lays out every visible node with a parent-child edge and finite positions', () => {
    const { nodes, edges } = buildLayout(root, new Set(), 'LR');
    expect(nodes).toHaveLength(countTreeNodes(root));
    expect(edges).toHaveLength(countTreeNodes(root) - 1);
    for (const node of nodes) {
      expect(Number.isFinite(node.position.x)).toBe(true);
      expect(Number.isFinite(node.position.y)).toBe(true);
      expect(node.type).toBe('mind');
      expect(node.data.depth).toBeGreaterThanOrEqual(0);
      expect((node.style as { width: number }).width).toBeGreaterThan(0);
    }
    const positions = new Map(nodes.map((node) => [node.id, node.position.x]));
    for (const edge of edges) {
      expect(positions.has(edge.source)).toBe(true);
      expect(positions.has(edge.target)).toBe(true);
      expect(positions.get(edge.target)!).toBeGreaterThan(positions.get(edge.source)!);
    }
  });

  it('supports a vertical layout', () => {
    const { nodes, edges } = buildLayout(root, new Set(), 'TB');
    const positions = new Map(nodes.map((node) => [node.id, node.position.y]));
    for (const edge of edges) {
      expect(positions.get(edge.target)!).toBeGreaterThan(positions.get(edge.source)!);
    }
  });

  it('drops hidden descendants and their edges when collapsed', () => {
    const branch = root.children[1];
    const { nodes, edges } = buildLayout(root, new Set([branch.id]), 'LR');
    const visible = collectVisible(root, new Set([branch.id]));
    expect(nodes).toHaveLength(visible.length);
    expect(nodes.some((node) => node.id === branch.id)).toBe(true);
    for (const child of branch.children) {
      expect(nodes.some((node) => node.id === child.id)).toBe(false);
    }
    const nodeIds = new Set(nodes.map((node) => node.id));
    for (const edge of edges) {
      expect(nodeIds.has(edge.source)).toBe(true);
      expect(nodeIds.has(edge.target)).toBe(true);
    }
    const branchNode = nodes.find((node) => node.id === branch.id);
    expect(branchNode?.data.collapsed).toBe(true);
    expect(branchNode?.data.hasChildren).toBe(true);
  });

  it('assigns each branch and its descendants one palette color', () => {
    const { nodes } = buildLayout(root, new Set(), 'LR');
    const branch = root.children[0];
    const branchNode = nodes.find((node) => node.id === branch.id);
    const childNode = nodes.find((node) => node.id === branch.children[0].id);
    expect(branchNode?.data.color).toBe(childNode?.data.color);
    const other = findNode(root, root.children[1].id);
    const otherNode = nodes.find((node) => node.id === other?.id);
    expect(otherNode?.data.color).not.toBe(branchNode?.data.color);
  });
});
