import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';

import { MAX_UPLOAD_MB } from '../lib/stages';
import type { GenerationOptions } from '../types/mindmap';
import { AlertIcon, FileIcon, GlobeIcon, SparklesIcon, UploadIcon } from './icons';

interface FileUploadProps {
  busy: boolean;
  serverError: string | null;
  llmWarning?: string | null;
  onStart: (file: File, options: GenerationOptions) => void;
  onSample: () => void;
}

const LANGUAGES = [
  { value: '', label: 'Match document' },
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Russian' },
  { value: 'kk', label: 'Kazakh' },
  { value: 'de', label: 'German' },
  { value: 'fr', label: 'French' },
  { value: 'es', label: 'Spanish' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ja', label: 'Japanese' },
  { value: 'ar', label: 'Arabic' },
];

function validateFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    return 'Only .pdf files are supported.';
  }
  if (file.type && file.type !== 'application/pdf' && file.type !== 'application/x-pdf') {
    return 'That file does not look like a PDF (wrong content type).';
  }
  if (file.size === 0) {
    return 'The selected file is empty.';
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `The file is too large. The limit is ${MAX_UPLOAD_MB} MB.`;
  }
  return null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileUpload({
  busy,
  serverError,
  llmWarning,
  onStart,
  onSample,
}: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [language, setLanguage] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const acceptFile = (candidate: File | undefined) => {
    if (!candidate) return;
    const validationError = validateFile(candidate);
    if (validationError) {
      setError(validationError);
      setFile(null);
      return;
    }
    setError(null);
    setFile(candidate);
  };

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    acceptFile(event.target.files?.[0]);
    event.target.value = '';
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    acceptFile(event.dataTransfer.files?.[0]);
  };

  const visibleError = error ?? serverError;

  return (
    <div className="upload-screen">
      <section className="upload-hero-wrap">
        <div className="upload-hero">
          <span className="eyebrow">
            <SparklesIcon size={15} /> PDF → knowledge map
          </span>
          <h1>
            Turn any PDF into
            <br />
            <span className="gradient-text">a map of ideas.</span>
          </h1>
          <p className="upload-hero__lead">
            A concept-first study map: categories stay clean, every leaf explains a real idea
            from the document, and every explanation keeps its source pages.
          </p>
          <div className="hero-pills">
            <span>Semantic clustering</span>
            <span>Visible explanations</span>
            <span>Source citations</span>
          </div>
        </div>
      </section>

      <div className="upload-body">
        <div className="upload-card">
          {llmWarning ? (
            <div className="inline-warning" role="status">
              <AlertIcon size={17} />
              <span>{llmWarning}</span>
            </div>
          ) : null}
          <label
            className={`dropzone ${dragging ? 'is-dragging' : ''} ${file ? 'has-file' : ''}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              onChange={onInputChange}
              hidden
            />
            {file ? (
              <div className="file-summary">
                <span className="file-summary__icon">
                  <FileIcon size={26} />
                </span>
                <div className="file-summary__text">
                  <strong>{file.name}</strong>
                  <span>{formatBytes(file.size)} · ready to generate</span>
                </div>
                <button
                  type="button"
                  className="link-button"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setFile(null);
                    setError(null);
                  }}
                >
                  Remove
                </button>
              </div>
            ) : (
              <div className="dropzone__inner">
                <span className="dropzone__icon">
                  <UploadIcon size={28} />
                </span>
                <strong>Drop your PDF here</strong>
                <span className="dropzone__hint">
                  or click to browse · up to {MAX_UPLOAD_MB} MB
                </span>
              </div>
            )}
          </label>

          <div className="language-row">
            <label className="field">
              <span className="field__label">
                <GlobeIcon size={13} /> Output language
              </span>
              <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                {LANGUAGES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {visibleError && (
            <div className="inline-error" role="alert">
              <AlertIcon size={17} />
              <span>{visibleError}</span>
            </div>
          )}

          <button
            type="button"
            className="primary-button primary-button--wide"
            disabled={!file || busy}
            onClick={() => {
              if (!file) {
                setError('Choose a PDF first.');
                return;
              }
              onStart(file, { language: language || undefined });
            }}
          >
            {busy ? 'Starting…' : 'Generate mind map'}
            <SparklesIcon size={17} />
          </button>

          <div className="upload-card__footer">
            <span>Text-based PDFs only · scanned PDFs need OCR</span>
            <button type="button" className="link-button" onClick={onSample}>
              Explore a sample map →
            </button>
          </div>
        </div>

        <div className="feature-row">
          <article className="feature">
            <span className="feature__index">01</span>
            <strong>Concept-first</strong>
            <span>
              Terms are extracted from the document, then clustered into meaningful categories —
              not copied from section headings.
            </span>
          </article>
          <article className="feature">
            <span className="feature__index">02</span>
            <strong>Readable leaves</strong>
            <span>
              Every leaf carries its explanation on the map itself, so exports keep the content
              instead of hiding it behind a click.
            </span>
          </article>
          <article className="feature">
            <span className="feature__index">03</span>
            <strong>Traceable</strong>
            <span>
              Evidence quotes are checked against the cited pages; learning objectives and
              activities stay out of the tree.
            </span>
          </article>
        </div>
      </div>
    </div>
  );
}
