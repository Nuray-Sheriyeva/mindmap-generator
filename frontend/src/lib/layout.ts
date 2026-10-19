/** Dagre-based tree layout → React Flow nodes/edges. Pure and testable. */

import dagre from 'dagre';
import type { Edge, Node } from '@xyflow/react';

import type { MindMapNode } from '../types/mindmap';
import { collectVisible, colorForBranch, ROOT_COLOR } from './tree';

export type LayoutDirection = 'LR' | 'TB';

export interface MindMapNodeData extends Record<string, unknown> {
  node: MindMapNode;
  depth: number;
  branchIndex: number;
  color: string;
  collapsed: boolean;
  hasChildren: boolean;
  childCount: number;
  direction: LayoutDirection;
}

export type MindMapFlowNode = Node<MindMapNodeData, 'mind'>;

export interface LayoutResult {
  nodes: MindMapFlowNode[];
  edges: Edge[];
}

const NODE_HEIGHT = 68;
const ROOT_HEIGHT = 78;

export function nodeWidth(label: string, depth: number): number {
  const base = depth === 0 ? 220 : 168;
  const extra = Math.min(110, Math.max(0, label.length - 16) * 5);
  return Math.min(depth === 0 ? 300 : 268, base + extra);
}

export function buildLayout(
  root: MindMapNode,
  collapsed: ReadonlySet<string>,
  direction: LayoutDirection = 'LR',
): LayoutResult {
  const visible = collectVisible(root, collapsed);
  const sizes = new Map<string, { width: number; height: number }>();
  const colors = new Map<string, string>();

  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: direction,
    nodesep: direction === 'LR' ? 28 : 44,
    ranksep: direction === 'LR' ? 88 : 76,
    marginx: 32,
    marginy: 32,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const { node, depth, branchIndex } of visible) {
    const width = nodeWidth(node.label, depth);
    const height = depth === 0 ? ROOT_HEIGHT : NODE_HEIGHT;
    sizes.set(node.id, { width, height });
    colors.set(node.id, colorForBranch(branchIndex));
    graph.setNode(node.id, { width, height });
  }

  for (const { node } of visible) {
    for (const child of node.children) {
      if (!sizes.has(child.id)) continue;
      graph.setEdge(node.id, child.id);
      colors.set(child.id, colors.get(child.id) ?? ROOT_COLOR);
    }
  }

  dagre.layout(graph);

  const nodes: MindMapFlowNode[] = visible.map(({ node, depth, branchIndex }) => {
    const size = sizes.get(node.id) ?? { width: 180, height: NODE_HEIGHT };
    const position = graph.node(node.id) as { x: number; y: number } | undefined;
    const x = (position?.x ?? 0) - size.width / 2;
    const y = (position?.y ?? 0) - size.height / 2;
    return {
      id: node.id,
      type: 'mind',
      position: { x, y },
      data: {
        node,
        depth,
        branchIndex,
        color: colors.get(node.id) ?? ROOT_COLOR,
        collapsed: collapsed.has(node.id),
        hasChildren: node.children.length > 0,
        childCount: node.children.length,
        direction,
      },
      style: { width: size.width, height: size.height },
      draggable: true,
      selectable: true,
      ariaLabel: `${node.label}, ${node.children.length} children`,
    };
  });

  const edges: Edge[] = [];
  for (const { node } of visible) {
    for (const child of node.children) {
      if (!sizes.has(child.id)) continue;
      const color = colors.get(child.id) ?? ROOT_COLOR;
      edges.push({
        id: `edge-${node.id}-${child.id}`,
        source: node.id,
        target: child.id,
        type: 'smoothstep',
        style: { stroke: color, strokeWidth: 1.7, opacity: 0.65 },
      });
    }
  }

  return { nodes, edges };
}
