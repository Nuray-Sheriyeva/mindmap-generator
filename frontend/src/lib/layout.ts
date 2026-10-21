/** Dagre-based tree layout → React Flow nodes/edges. Pure and testable. */

import dagre from 'dagre';
import type { Edge, Node } from '@xyflow/react';

import type { MindMapNode, NodeKind } from '../types/mindmap';
import { collectVisible, colorForBranch, ROOT_COLOR } from './tree';

export type LayoutDirection = 'LR' | 'TB';

export interface MindMapNodeData extends Record<string, unknown> {
  node: MindMapNode;
  kind: NodeKind;
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

export function nodeWidth(node: MindMapNode, depth: number): number {
  if (depth === 0) return 260;
  if (node.kind === 'leaf') {
    const extra = Math.min(60, Math.max(0, (node.explanation?.length ?? 0) - 100) * 0.12);
    return Math.round(288 + extra);
  }
  const extra = Math.min(50, Math.max(0, node.label.length - 18) * 4);
  return 178 + extra;
}

export function nodeHeight(node: MindMapNode, depth: number): number {
  if (depth === 0) return 74;
  if (node.kind !== 'leaf') return 54;
  const length = node.explanation?.length ?? 0;
  const lines = Math.max(2, Math.min(4, Math.ceil(length / 46)));
  return 84 + lines * 15;
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
    nodesep: direction === 'LR' ? 30 : 38,
    ranksep: direction === 'LR' ? 105 : 84,
    marginx: 40,
    marginy: 40,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const { node, depth, branchIndex } of visible) {
    const width = nodeWidth(node, depth);
    const height = nodeHeight(node, depth);
    sizes.set(node.id, { width, height });
    colors.set(node.id, colorForBranch(branchIndex));
    graph.setNode(node.id, { width, height });
  }

  for (const { node } of visible) {
    for (const child of node.children) {
      if (!sizes.has(child.id)) continue;
      graph.setEdge(node.id, child.id);
    }
  }

  dagre.layout(graph);

  const nodes: MindMapFlowNode[] = visible.map(({ node, depth, branchIndex }) => {
    const size = sizes.get(node.id) ?? { width: 280, height: 100 };
    const position = graph.node(node.id) as { x: number; y: number } | undefined;
    const x = (position?.x ?? 0) - size.width / 2;
    const y = (position?.y ?? 0) - size.height / 2;
    const color = colors.get(node.id) ?? ROOT_COLOR;
    return {
      id: node.id,
      type: 'mind',
      position: { x, y },
      data: {
        node,
        kind: node.kind,
        depth,
        branchIndex,
        color,
        collapsed: collapsed.has(node.id),
        hasChildren: node.children.length > 0,
        childCount: node.children.length,
        direction,
      },
      style: { width: size.width, height: size.height },
      draggable: true,
      selectable: false,
      focusable: false,
      ariaLabel:
        node.kind === 'leaf'
          ? `${node.label}: ${node.explanation ?? ''}`
          : `${node.label}, ${node.children.length} branches`,
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
        type: 'default',
        style: { stroke: color, strokeWidth: 1.6, opacity: 0.55 },
      });
    }
  }

  return { nodes, edges };
}
