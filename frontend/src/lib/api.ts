/** Typed client for the mind map backend. */

import type {
  GenerationOptions,
  HealthResponse,
  JobResponse,
  MindMapResult,
} from '../types/mindmap';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
export const API_BASE = RAW_BASE.replace(/\/$/, '');

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = 'error') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

interface ErrorEnvelope {
  error?: { message?: string; code?: string };
}

async function readError(response: Response): Promise<ApiError> {
  let body: ErrorEnvelope | null = null;
  try {
    body = (await response.json()) as ErrorEnvelope;
  } catch {
    body = null;
  }
  const message =
    body?.error?.message ??
    `Request failed with status ${response.status}. Is the backend running?`;
  return new ApiError(message, response.status, body?.error?.code ?? 'error');
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`, { signal });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as HealthResponse;
}

export async function createMindMap(
  file: File,
  options: GenerationOptions,
  signal?: AbortSignal,
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('file', file);
  if (options.language) {
    form.append('language', options.language);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/mindmaps`, {
      method: 'POST',
      body: form,
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(
      'Could not reach the backend. Start it with `uv run uvicorn ...` and retry.',
      0,
      'network_error',
    );
  }
  if (!response.ok) throw await readError(response);
  return (await response.json()) as { job_id: string };
}

export async function getMindMapJob(jobId: string, signal?: AbortSignal): Promise<JobResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/mindmaps/${encodeURIComponent(jobId)}`, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Lost connection to the backend while polling the job.', 0, 'network_error');
  }
  if (!response.ok) throw await readError(response);
  return (await response.json()) as JobResponse;
}

export function exportUrl(jobId: string, format: 'json' | 'markdown'): string {
  return `${API_BASE}/mindmaps/${encodeURIComponent(jobId)}/export?format=${format}`;
}

export function resultFilename(result: MindMapResult, extension: string): string {
  const stem = result.document.filename.replace(/\.pdf$/i, '') || 'document';
  return `${stem}-mindmap.${extension}`;
}
