import { describe, expect, it } from 'vitest';

import { SAMPLE_RESULT } from '../data/sample';
import { exportFilename, toJson, toMarkdown } from './exports';

describe('Markdown export', () => {
  it('renders a hierarchical outline with summaries and page citations', () => {
    const markdown = toMarkdown(SAMPLE_RESULT);
    expect(markdown).toContain('# Photosynthesis');
    expect(markdown).toContain('## Introduction');
    expect(markdown).toContain('### Definition');
    expect(markdown).toContain('#### Energy conversion');
    expect(markdown).toContain('_Source pages: 1–2_');
    expect(markdown).toContain('> Source: `photosynthesis-primer.pdf` · 8 page(s) · language: en');
    expect(markdown.trim().endsWith('>')).toBe(false);
  });
});

describe('JSON export', () => {
  it('round-trips the canonical result', () => {
    const parsed = JSON.parse(toJson(SAMPLE_RESULT));
    expect(parsed.mindmap.label).toBe('Photosynthesis');
    expect(parsed.document.pages).toBe(8);
    expect(parsed.meta.node_count).toBe(SAMPLE_RESULT.meta.node_count);
  });
});

describe('export filenames', () => {
  it('replaces the PDF extension', () => {
    expect(exportFilename(SAMPLE_RESULT, 'json')).toBe('photosynthesis-primer-mindmap.json');
    expect(exportFilename(SAMPLE_RESULT, 'svg')).toBe('photosynthesis-primer-mindmap.svg');
  });
});
