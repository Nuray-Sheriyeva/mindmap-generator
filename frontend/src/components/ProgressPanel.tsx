import type { JobResponse } from '../types/mindmap';
import { PIPELINE_STAGES } from '../lib/stages';
import { AlertIcon, CheckIcon, FileIcon, SparklesIcon } from './icons';

interface ProgressPanelProps {
  job: JobResponse | null;
  filename: string;
  error: string | null;
  onBack: () => void;
}

export function ProgressPanel({ job, filename, error, onBack }: ProgressPanelProps) {
  const currentIndex = job ? Math.max(0, job.stage_index - 1) : -1;
  const failed = Boolean(error) || job?.status === 'failed';
  const progress = failed ? 0 : Math.round((job?.progress ?? 0) * 100);

  return (
    <div className="progress-screen">
      <div className="progress-card">
        <span className="progress-kicker">Concept-first pipeline</span>
        <div className="progress-card__header">
          <div className="progress-file">
            <span className="progress-file__icon">
              <FileIcon size={22} />
            </span>
            <div>
              <strong>{filename || job?.filename || 'Your PDF'}</strong>
              <span>
                {failed
                  ? 'Generation stopped'
                  : job?.stage_label
                    ? `${job.stage_label}…`
                    : 'Queued for generation'}
              </span>
            </div>
          </div>
          {!failed && (
            <div className="spinner" aria-label="Generating">
              <span />
            </div>
          )}
        </div>

        {failed ? (
          <div className="progress-error" role="alert">
            <span className="progress-error__icon">
              <AlertIcon size={22} />
            </span>
            <div>
              <strong>We couldn't finish this mind map</strong>
              <p>{error ?? job?.error?.message ?? 'An unexpected error occurred.'}</p>
              {job?.error?.code ? <code className="error-code">{job.error.code}</code> : null}
            </div>
          </div>
        ) : (
          <>
            <div
              className="progress-bar"
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <span style={{ width: `${Math.max(progress, job ? 3 : 2)}%` }} />
            </div>
            <div className="progress-meta">
              <span>{progress}%</span>
              <span>{job?.cache_hit ? 'Cache hit' : 'Grounded concept extraction'}</span>
            </div>
            <ol className="stage-list">
              {PIPELINE_STAGES.map((stage, index) => {
                const done = index < currentIndex || job?.status === 'completed';
                const active = index === currentIndex && job?.status !== 'completed';
                return (
                  <li
                    key={stage.key}
                    className={`stage ${done ? 'is-done' : ''} ${active ? 'is-active' : ''}`}
                  >
                    <span className="stage__marker">
                      {done ? <CheckIcon size={13} /> : index + 1}
                    </span>
                    <div className="stage__text">
                      <strong>{stage.label}</strong>
                      <span>{stage.description}</span>
                    </div>
                    {active && <span className="stage__pulse" aria-hidden="true" />}
                  </li>
                );
              })}
            </ol>
          </>
        )}

        <div className="progress-card__footer">
          <span>
            <SparklesIcon size={14} /> Long documents take longer — polling every second.
          </span>
          <button type="button" className="secondary-button" onClick={onBack}>
            {failed ? 'Try another PDF' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  );
}
