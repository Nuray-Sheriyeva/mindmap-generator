import { useCallback, useEffect, useRef, useState } from 'react';

import { FileUpload } from './components/FileUpload';
import { MindMapCanvas, type FlowExportApi } from './components/MindMapCanvas';
import { ProgressPanel } from './components/ProgressPanel';
import {
  ArrowLeftIcon,
  ChevronIcon,
  CollapseIcon,
  DownloadIcon,
  ExpandIcon,
  FitIcon,
} from './components/icons';
import { SAMPLE_RESULT } from './data/sample';
import { ApiError, createMindMap, getHealth, getMindMapJob } from './lib/api';
import { downloadMindMap } from './lib/exports';
import type { LayoutDirection } from './lib/layout';
import { collectIdsWithChildren, toggleCollapsed } from './lib/tree';
import type { GenerationOptions, JobResponse, MindMapResult } from './types/mindmap';

type Screen = 'upload' | 'generating' | 'map';
type ExportFormat = 'json' | 'markdown' | 'png' | 'svg';

interface UiError {
  message: string;
  code?: string;
}

interface Toast {
  message: string;
  kind: 'info' | 'error';
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('upload');
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [result, setResult] = useState<MindMapResult | null>(null);
  const [filename, setFilename] = useState('');
  const [error, setError] = useState<UiError | null>(null);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [direction, setDirection] = useState<LayoutDirection>('LR');
  const [fitSignal, setFitSignal] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [sampleMode, setSampleMode] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const flowExportRef = useRef<FlowExportApi | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!jobId || screen !== 'generating') return;
    let active = true;
    let attempts = 0;
    let timer: number | undefined;
    const controller = new AbortController();

    const poll = async () => {
      try {
        const next = await getMindMapJob(jobId, controller.signal);
        if (!active) return;
        setJob(next);
        if (next.status === 'completed' && next.result) {
          setResult(next.result);
          setFilename(next.result.document.filename);
          setCollapsed(new Set());
          setScreen('map');
          setJobId(null);
          setError(null);
          return;
        }
        if (next.status === 'failed') {
          setError({
            message: next.error?.message ?? 'Generation failed.',
            code: next.error?.code,
          });
          return;
        }
        attempts = 0;
        timer = window.setTimeout(poll, 1000);
      } catch (caught) {
        if (!active) return;
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        if (caught instanceof ApiError) {
          setError({ message: caught.message, code: caught.code });
          return;
        }
        attempts += 1;
        if (attempts >= 3) {
          setError({
            message: 'Lost connection to the backend while polling the job.',
            code: 'network_error',
          });
          return;
        }
        timer = window.setTimeout(poll, 1500);
      }
    };

    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId, screen]);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setLlmConfigured(health.llm_configured))
      .catch(() => setLlmConfigured(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!exportOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setExportOpen(false);
      }
    };
    window.addEventListener('mousedown', onPointerDown);
    return () => window.removeEventListener('mousedown', onPointerDown);
  }, [exportOpen]);

  const reset = useCallback(() => {
    setScreen('upload');
    setJobId(null);
    setJob(null);
    setResult(null);
    setFilename('');
    setError(null);
    setCollapsed(new Set());
    setExportOpen(false);
    setExporting(null);
    setSampleMode(false);
  }, []);

  const handleStart = useCallback(async (file: File, options: GenerationOptions) => {
    setError(null);
    setJob(null);
    setFilename(file.name);
    setSampleMode(false);
    setScreen('generating');
    try {
      const created = await createMindMap(file, options);
      setJobId(created.job_id);
    } catch (caught) {
      const message =
        caught instanceof ApiError
          ? caught.message
          : 'Could not upload the PDF. Please try again.';
      setError({ message, code: caught instanceof ApiError ? caught.code : 'upload_error' });
    }
  }, []);

  const handleSample = useCallback(() => {
    setResult(SAMPLE_RESULT);
    setFilename(SAMPLE_RESULT.document.filename);
    setScreen('map');
    setSampleMode(true);
    setError(null);
    setJob(null);
    setJobId(null);
    setCollapsed(new Set());
  }, []);

  const handleToggle = useCallback((id: string) => {
    setCollapsed((current) => toggleCollapsed(current, id));
  }, []);

  const handleCollapseAll = useCallback(() => {
    if (!result) return;
    setCollapsed(
      new Set(collectIdsWithChildren(result.mindmap).filter((id) => id !== result.mindmap.id)),
    );
  }, [result]);

  const handleExport = useCallback(
    async (format: ExportFormat) => {
      if (!result) return;
      setExportOpen(false);
      if (format === 'json' || format === 'markdown') {
        downloadMindMap(result, format);
        setToast({
          message: `${format === 'json' ? 'JSON' : 'Markdown'} export downloaded.`,
          kind: 'info',
        });
        return;
      }
      setExporting(format);
      try {
        if (!flowExportRef.current) throw new Error('Canvas is not ready yet.');
        await flowExportRef.current.exportImage(format);
        setToast({ message: `${format.toUpperCase()} snapshot downloaded.`, kind: 'info' });
      } catch {
        setToast({
          message: `Could not export ${format.toUpperCase()}. Try again after the canvas settles.`,
          kind: 'error',
        });
      } finally {
        setExporting(null);
      }
    },
    [result],
  );

  const showHeaderActions = screen === 'map' && result !== null;

  return (
    <div
      className={`app ${screen === 'map' ? 'app--map' : ''} ${
        screen === 'upload' ? 'app--upload' : ''
      }`}
    >
      <header className="app-header">
        <div className="app-header__bar">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" width="22" height="22">
                <circle cx="16" cy="16" r="4" fill="currentColor" />
                <circle cx="6" cy="6" r="2.6" fill="currentColor" opacity=".85" />
                <circle cx="26" cy="6" r="2.6" fill="currentColor" opacity=".85" />
                <circle cx="6" cy="26" r="2.6" fill="currentColor" opacity=".85" />
                <circle cx="26" cy="26" r="2.6" fill="currentColor" opacity=".85" />
                <path
                  d="M16 16 6 6m10 10L26 6M16 16 6 26m10-10 10 10"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  opacity=".7"
                />
              </svg>
            </span>
            <div className="brand__text">
              <strong>Mind Map</strong>
              <span>PDF knowledge studio</span>
            </div>
          </div>

          {showHeaderActions && result && (
            <div className="doc-chip" title={filename}>
              <span className="doc-chip__dot" />
              <span className="doc-chip__name">{result.document.title || filename}</span>
              <span className="doc-chip__meta">
                {result.document.pages} pages · {result.document.language.toUpperCase()}
                {sampleMode ? ' · sample' : ''}
              </span>
            </div>
          )}

          <div className="header-actions">
            {showHeaderActions ? (
              <>
                <button
                  type="button"
                  className="tool-button tool-button--icon"
                  title={
                    direction === 'LR'
                      ? 'Switch to vertical layout'
                      : 'Switch to horizontal layout'
                  }
                  onClick={() => setDirection((current) => (current === 'LR' ? 'TB' : 'LR'))}
                >
                  {direction === 'LR' ? <ExpandIcon size={16} /> : <CollapseIcon size={16} />}
                  <span>{direction === 'LR' ? 'Vertical' : 'Horizontal'}</span>
                </button>
                <button
                  type="button"
                  className="tool-button tool-button--icon"
                  onClick={() => setFitSignal((value) => value + 1)}
                >
                  <FitIcon size={16} />
                  <span>Fit</span>
                </button>
                <div className="export-menu" ref={menuRef}>
                  <button
                    type="button"
                    className="primary-button primary-button--small"
                    aria-haspopup="menu"
                    aria-expanded={exportOpen}
                    onClick={() => setExportOpen((open) => !open)}
                    disabled={exporting !== null}
                  >
                    <DownloadIcon size={16} />
                    {exporting ? `Exporting ${exporting.toUpperCase()}…` : 'Export'}
                    <ChevronIcon size={14} />
                  </button>
                  {exportOpen && (
                    <div className="export-dropdown" role="menu">
                      <button type="button" role="menuitem" onClick={() => void handleExport('json')}>
                        <strong>JSON</strong>
                        <span>Full canonical result</span>
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => void handleExport('markdown')}
                      >
                        <strong>Markdown</strong>
                        <span>Outline with leaf explanations</span>
                      </button>
                      <button type="button" role="menuitem" onClick={() => void handleExport('png')}>
                        <strong>PNG</strong>
                        <span>Current view snapshot</span>
                      </button>
                      <button type="button" role="menuitem" onClick={() => void handleExport('svg')}>
                        <strong>SVG</strong>
                        <span>Vector snapshot</span>
                      </button>
                    </div>
                  )}
                </div>
                <button type="button" className="tool-button" onClick={reset}>
                  <ArrowLeftIcon size={16} />
                  <span>New PDF</span>
                </button>
              </>
            ) : screen === 'generating' ? (
              <button type="button" className="tool-button" onClick={reset}>
                <ArrowLeftIcon size={16} />
                <span>Back</span>
              </button>
            ) : null}
          </div>
        </div>
      </header>

      {screen === 'upload' && (
        <FileUpload
          busy={false}
          serverError={error?.message ?? null}
          llmWarning={
            llmConfigured === false
              ? 'The backend has no LLM API key. Add API_KEY=... to backend/.env and restart the backend, or run it with LLM_PROVIDER=mock for the offline demo.'
              : null
          }
          onStart={handleStart}
          onSample={handleSample}
        />
      )}

      {screen === 'generating' && (
        <ProgressPanel
          job={job}
          filename={filename}
          error={error?.message ?? null}
          onBack={reset}
        />
      )}

      {screen === 'map' && result && (
        <main className="map-screen">
          <div className="map-tip">Click branch arrows to expand · drag to pan · scroll to zoom</div>
          <MindMapCanvas
            result={result}
            collapsed={collapsed}
            direction={direction}
            fitSignal={fitSignal}
            exportRef={flowExportRef}
            onToggle={handleToggle}
            onExpandAll={() => setCollapsed(new Set())}
            onCollapseAll={handleCollapseAll}
          />
        </main>
      )}

      {toast && (
        <div className={`toast toast--${toast.kind}`} role="status">
          {toast.message}
        </div>
      )}
    </div>
  );
}
