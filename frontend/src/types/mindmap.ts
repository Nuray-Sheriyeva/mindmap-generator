/** Types mirroring the backend's canonical schema (keep both sides in sync). */

export interface MindMapNode {
  id: string;
  label: string;
  summary: string;
  source_pages: number[];
  children: MindMapNode[];
}

export interface DocumentInfo {
  filename: string;
  pages: number;
  language: string;
  title?: string | null;
}

export interface MindMapMeta {
  model: string;
  generated_at: string;
  node_count: number;
  depth: number;
  cache_hit?: boolean;
  repair_attempts?: number;
  generation_path?: 'single_call' | 'map_reduce' | 'unknown';
  output_language?: string | null;
  processing_ms?: number;
  fixes?: string[];
}

export interface MindMapResult {
  document: DocumentInfo;
  mindmap: MindMapNode;
  meta: MindMapMeta;
}

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface JobError {
  code: string;
  message: string;
  status_code: number;
  details?: Record<string, unknown>;
}

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  stage: string | null;
  stage_label: string | null;
  stage_index: number;
  total_stages: number;
  progress: number;
  filename: string;
  file_hash: string;
  cache_hit: boolean;
  error: JobError | null;
  result: MindMapResult | null;
  created_at: string;
  updated_at: string;
}

export interface GenerationOptions {
  maxDepth: number;
  maxBranches: number;
  language?: string;
}

export interface PipelineStage {
  key: string;
  label: string;
  description: string;
}
