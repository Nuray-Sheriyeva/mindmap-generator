/** Types mirroring the backend schema v2 (keep both sides in sync). */

export type NodeKind = 'root' | 'branch' | 'leaf';

export interface MindMapNode {
  id: string;
  kind: NodeKind;
  label: string;
  explanation?: string | null;
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
  schema_version: number;
  model: string;
  generated_at: string;
  node_count: number;
  leaf_count: number;
  branch_count: number;
  depth: number;
  cache_hit?: boolean;
  repair_attempts?: number;
  generation_path?: string;
  output_language?: string | null;
  processing_ms?: number;
  fixes?: string[];
  warnings?: string[];
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

/** The upload UI only exposes the output-language choice. */
export interface GenerationOptions {
  language?: string;
}

export interface HealthResponse {
  status: 'ok';
  app: string;
  version: string;
  environment: string;
  llm_provider: string;
  llm_model: string;
  llm_configured: boolean;
  cache_enabled: boolean;
}

export interface PipelineStage {
  key: string;
  label: string;
  description: string;
}
