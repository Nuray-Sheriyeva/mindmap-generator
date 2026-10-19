import { describe, expect, it } from 'vitest';

import { SAMPLE_RESULT } from '../data/sample';
import {
  BRANCH_COLORS,
  collectIdsWithChildren,
  collectVisible,
  colorForBranch,
  countTreeNodes,
  findNode,
  findPathLabels,
  formatPages,
  toggleCollapsed,
  treeDepth,
} from './tree';

const root = SAMPLE_RESULT.mindmap;

describe('tree helpers', () => {
  it('counts nodes and depth from the sample', () => {
    expect(countTreeNodes(root)).toBe(SAMPLE_RESULT.meta.node_count);
    expect(treeDepth(root)).toBe(3);
  });

  it('collects all visible nodes when nothing is collapsed', () => {
    const visible = collectVisible(root, new Set());
    expect(visible).toHaveLength(countTreeNodes(root));
    expect(visible[0]).toMatchObject({ depth: 0, branchIndex: -1 });
    expect(visible[1]).toMatchObject({ depth: 1, branchIndex: 0 });
    expect(new Set(visible.map((entry) => entry.node.id)).size).toBe(visible.length);
  });

  it('hides descendants of collapsed nodes but keeps the node itself', () => {
    const branch = root.children[1];
    const hiddenIds = collectIdsWithChildren(branch);
    const visible = collectVisible(root, new Set([branch.id]));
    const ids = new Set(visible.map((entry) => entry.node.id));
    expect(ids.has(branch.id)).toBe(true);
    hiddenIds.forEach((id) => {
      if (id !== branch.id) expect(ids.has(id)).toBe(false);
    });
    expect(visible.length).toBeLessThan(countTreeNodes(root));
  });

  it('finds nodes and root-to-node label paths', () => {
    const target = root.children[1].children[0];
    expect(findNode(root, target.id)?.label).toBe(target.label);
    expect(findNode(root, 'missing')).toBeNull();
    expect(findNode(root, null)).toBeNull();
    expect(findPathLabels(root, target.id)).toEqual([
      root.label,
      root.children[1].label,
      target.label,
    ]);
  });

  it('collects collapsible ids including nested nodes', () => {
    const ids = collectIdsWithChildren(root);
    expect(ids).toContain(root.id);
    expect(ids).toContain(root.children[0].id);
    expect(ids.length).toBeGreaterThan(root.children.length);
  });

  it('toggles collapsed state immutably', () => {
    const first = toggleCollapsed(new Set(), 'root.1');
    expect(first.has('root.1')).toBe(true);
    const second = toggleCollapsed(first, 'root.1');
    expect(second.has('root.1')).toBe(false);
    expect(first.has('root.1')).toBe(true);
  });
});

describe('formatPages', () => {
  it('formats and deduplicates ranges', () => {
    expect(formatPages([1, 2, 3, 5])).toBe('1–3, 5');
    expect(formatPages([4, 2, 2])).toBe('2, 4');
    expect(formatPages([1])).toBe('1');
    expect(formatPages([])).toBe('');
  });
});

describe('branch colors', () => {
  it('cycles the palette and uses a neutral root color', () => {
    expect(colorForBranch(-1)).toBe('#334155');
    expect(colorForBranch(0)).toBe(BRANCH_COLORS[0]);
    expect(colorForBranch(BRANCH_COLORS.length)).toBe(BRANCH_COLORS[0]);
  });
});
