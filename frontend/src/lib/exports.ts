/** Result exporters: JSON, Markdown outline and PNG/SVG snapshots. */

import type { MindMapNode, MindMapResult } from '../types/mindmap';
import { formatPages } from './tree';

function renderNode(node: MindMapNode, level: number, lines: string[]): void {
  lines.push(`${'#'.repeat(Math.min(level, 6))} ${node.label}`);
  const summary = node.summary?.trim();
  if (summary) {
    lines.push('', summary);
  }
  const pages = formatPages(node.source_pages);
  if (pages) {
    lines.push('', `_Source pages: ${pages}_`);
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

function isChromeNode(node: Node): boolean {
  const element = node as HTMLElement;
  if (!element.classList) return false;
  return ['react-flow__controls', 'react-flow__minimap', 'react-flow__attribution', 'react-flow__panel'].some(
    (name) => element.classList.contains(name),
  );
}

/** Capture the current flow viewport as PNG or SVG using html-to-image. */
export async function downloadFlowImage(
  element: HTMLElement,
  result: MindMapResult,
  format: 'png' | 'svg',
): Promise<void> {
  const { toPng, toSvg } = await import('html-to-image');
  const options = {
    backgroundColor: '#f6f8fc',
    pixelRatio: 2,
    cacheBust: true,
    filter: (node: Node) => !isChromeNode(node),
  };
  const dataUrl =
    format === 'png' ? await toPng(element, options) : await toSvg(element, options);
  const anchor = document.createElement('a');
  anchor.href = dataUrl;
  anchor.download = exportFilename(result, format);
  anchor.click();
}
