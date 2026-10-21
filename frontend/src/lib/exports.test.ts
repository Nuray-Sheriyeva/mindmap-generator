import { describe, expect, it } from 'vitest';

import { SAMPLE_RESULT } from '../data/sample';
import { exportFilename, toJson, toMarkdown } from './exports';

describe('Markdown export', () => {
  it('renders a hierarchical outline with summaries and page citations', () => {
    const markdown = toMarkdown(SAMPLE_RESULT);
    expect(markdown).toContain('# Large Language Models (LLMs)');
    expect(markdown).toContain('## Overview and Definition');
    expect(markdown).toContain('### Definition');
    expect(markdown).toContain('An LLM is an AI system trained on large collections of data');
    expect(markdown).toContain('### Important Limitations');
    expect(markdown).toContain('#### Hallucinations');
    expect(markdown).toContain('_Source pages: 4_');
    expect(markdown).toContain('> Source: `lesson-large-language-models.pdf` · 7 page(s) · language: en');
    expect(markdown.trim().endsWith('>')).toBe(false);
  });
});

describe('JSON export', () => {
  it('round-trips the canonical result', () => {
    const parsed = JSON.parse(toJson(SAMPLE_RESULT));
    expect(parsed.mindmap.label).toBe('Large Language Models (LLMs)');
    expect(parsed.document.pages).toBe(7);
    expect(parsed.meta.node_count).toBe(SAMPLE_RESULT.meta.node_count);
    expect(parsed.meta.schema_version).toBe(2);
    expect(parsed.meta.leaf_count).toBe(39);
  });
});

describe('export filenames', () => {
  it('replaces the PDF extension', () => {
    expect(exportFilename(SAMPLE_RESULT, 'json')).toBe('lesson-large-language-models-mindmap.json');
    expect(exportFilename(SAMPLE_RESULT, 'svg')).toBe('lesson-large-language-models-mindmap.svg');
  });
});
