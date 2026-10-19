import type { PipelineStage } from '../types/mindmap';

/** Mirrors the backend stage sequence (graph/state.py). */
export const PIPELINE_STAGES: PipelineStage[] = [
  { key: 'parse_pdf', label: 'Parse PDF', description: 'Extract text and detect headings' },
  { key: 'chunk_document', label: 'Chunk', description: 'Split into page-aware chunks' },
  {
    key: 'summarize_chunks',
    label: 'Summarize',
    description: 'Extract grounded concepts in parallel',
  },
  { key: 'build_hierarchy', label: 'Build tree', description: 'Reduce into one mind map' },
  {
    key: 'validate_and_repair',
    label: 'Validate',
    description: 'Check schema, depth and duplicates',
  },
  { key: 'finalize', label: 'Finalize', description: 'Assign IDs and metadata' },
];

export const MAX_UPLOAD_MB = 25;
