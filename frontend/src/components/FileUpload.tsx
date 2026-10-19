import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';

import { MAX_UPLOAD_MB } from '../lib/stages';
import type { GenerationOptions } from '../types/mindmap';
import { AlertIcon, FileIcon, SparklesIcon, UploadIcon } from './icons';

interface FileUploadProps {
  busy: boolean;
  serverError: string | null;
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

export function FileUpload({ busy, serverError, onStart, onSample }: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [maxDepth, setMaxDepth] = useState(3);
  const [maxBranches, setMaxBranches] = useState(6);
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
      <div className="upload-hero">
        <span className="eyebrow">
          <SparklesIcon size={15} /> PDF → interactive mind map
        </span>
        <h1>
          Turn any PDF into a <span className="gradient-text">map of ideas</span>
        </h1>
        <p className="upload-hero__lead">
          Upload a text-based PDF. The backend extracts its structure, finds the key concepts
          with an LLM, and renders a hierarchical map you can explore, collapse and export.
        </p>
      </div>

      <div className="upload-card">
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
              <span className="dropzone__hint">or click to browse · up to {MAX_UPLOAD_MB} MB</span>
            </div>
          )}
        </label>

        <div className="options-grid">
          <label className="field">
            <span className="field__label">Depth</span>
            <select
              value={maxDepth}
              onChange={(event) => setMaxDepth(Number(event.target.value))}
            >
              <option value={2}>2 levels below root</option>
              <option value={3}>3 levels below root</option>
            </select>
          </label>
          <label className="field">
            <span className="field__label">Main branches</span>
            <select
              value={maxBranches}
              onChange={(event) => setMaxBranches(Number(event.target.value))}
            >
              {[4, 5, 6, 7, 8].map((value) => (
                <option key={value} value={value}>
                  {value} branches
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Output language</span>
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
            onStart(file, {
              maxDepth,
              maxBranches,
              language: language || undefined,
            });
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
        <div className="feature">
          <span className="feature__dot" />
          <div>
            <strong>Grounded prompts</strong>
            <span>Only facts from your document, with page citations.</span>
          </div>
        </div>
        <div className="feature">
          <span className="feature__dot" />
          <div>
            <strong>Hierarchical by design</strong>
            <span>Central topic, main branches, sub-branches and leaf details.</span>
          </div>
        </div>
        <div className="feature">
          <span className="feature__dot" />
          <div>
            <strong>Yours to take</strong>
            <span>Export JSON, a Markdown outline, PNG or SVG.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
