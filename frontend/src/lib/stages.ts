import type { PipelineStage } from '../types/mindmap';

/** Mirrors the backend stage sequence (graph/state.py). */
export const PIPELINE_STAGES: PipelineStage[] = [
  { key: 'parse_pdf', label: 'Parse PDF', description: 'Extract pages and headings' },
  {
    key: 'classify_sections',
    label: 'Classify',
    description: 'Separate content from objectives and activities',
  },
  { key: 'chunk_document', label: 'Chunk', description: 'Split content into page-aware chunks' },
  {
    key: 'extract_concepts',
    label: 'Extract concepts',
    description: 'Grounded term → explanation cards',
  },
  {
    key: 'build_hierarchy',
    label: 'Cluster ideas',
    description: 'Group concepts into categories',
  },
  {
    key: 'validate_and_repair',
    label: 'Validate',
    description: 'Check grounding, style and coverage',
  },
  { key: 'finalize', label: 'Finalize', description: 'Assign IDs and metadata' },
];

export const MAX_UPLOAD_MB = 25;
