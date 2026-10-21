/** Result exporters: JSON, Markdown outline and PNG/SVG snapshots. */

import type { MindMapNode, MindMapResult } from '../types/mindmap';
import { formatPages } from './tree';

function renderNode(node: MindMapNode, level: number, lines: string[]): void {
  lines.push(`${'#'.repeat(Math.min(level, 6))} ${node.label}`);
  if (node.kind === 'leaf' && node.explanation?.trim()) {
    lines.push('', node.explanation.trim());
    const pages = formatPages(node.source_pages);
    if (pages) {
      lines.push('', `_Source pages: ${pages}_`);
    }
  }
  lines.push('');
  node.children.forEach((child) => renderNode(child, level + 1, lines));
}

export function toMarkdown(result: MindMapResult): string {
  const lines: string[] = [];
  renderNode(result.mindmap, 1, lines);
  lines.push(
    `> Source: \`${result.document.filename}\` · ${result.document.pages} page(s) · language: ${result.document.language}`,
  );
  const meta = [
    `model: ${result.meta.model}`,
    `generated: ${result.meta.generated_at}`,
    `nodes: ${result.meta.node_count}`,
    `leaves: ${result.meta.leaf_count}`,
  ];
  lines.push(`> ${meta.join(' · ')}`, '');
  return lines.join('\n');
}

export function toJson(result: MindMapResult): string {
  return JSON.stringify(result, null, 2);
}

export function exportFilename(result: MindMapResult, extension: string): string {
  const stem = result.document.filename.replace(/\.pdf$/i, '') || 'document';
  return `${stem}-mindmap.${extension}`;
}

export function downloadTextFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadMindMap(result: MindMapResult, format: 'json' | 'markdown'): void {
  if (format === 'json') {
    downloadTextFile(exportFilename(result, 'json'), toJson(result), 'application/json');
  } else {
    downloadTextFile(exportFilename(result, 'md'), toMarkdown(result), 'text/markdown');
  }
}
