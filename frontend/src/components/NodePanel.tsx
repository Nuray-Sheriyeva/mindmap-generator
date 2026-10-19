import { useEffect } from 'react';

import { formatPages, findPathLabels } from '../lib/tree';
import type { MindMapNode } from '../types/mindmap';
import { ChevronIcon, CloseIcon } from './icons';

interface NodePanelProps {
  node: MindMapNode;
  root: MindMapNode;
  onClose: () => void;
  onSelect: (id: string) => void;
}

export function NodePanel({ node, root, onClose, onSelect }: NodePanelProps) {
  const path = findPathLabels(root, node.id);
  const pages = formatPages(node.source_pages);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="panel-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="node-panel" role="dialog" aria-modal="false" aria-label={node.label}>
        <div className="node-panel__header">
          <div className="node-panel__heading">
            {path.length > 1 && (
              <nav className="node-panel__breadcrumb" aria-label="Breadcrumb">
                {path.slice(0, -1).map((label, index) => (
                  <span key={`${label}-${index}`} className="node-panel__crumb">
                    {label}
                  </span>
                ))}
              </nav>
            )}
            <h2>{node.label}</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Close details"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="node-panel__section">
          <h3 className="node-panel__label">Summary</h3>
          {node.summary ? (
            <p className="node-panel__summary">{node.summary}</p>
          ) : (
            <p className="node-panel__muted">No summary was generated for this node.</p>
          )}
        </div>

        <div className="node-panel__section">
          <h3 className="node-panel__label">Source pages</h3>
          {node.source_pages.length > 0 ? (
            <div className="page-chips">
              {node.source_pages.map((page) => (
                <span key={page} className="page-chip">
                  Page {page}
                </span>
              ))}
            </div>
          ) : (
            <p className="node-panel__muted">No page reference available.</p>
          )}
          {pages ? <p className="node-panel__hint">Traceable to p. {pages} of the PDF.</p> : null}
        </div>

        {node.children.length > 0 && (
          <div className="node-panel__section node-panel__section--grow">
            <h3 className="node-panel__label">
              Sub-topics <span className="count-badge">{node.children.length}</span>
            </h3>
            <ul className="child-list">
              {node.children.map((child) => (
                <li key={child.id}>
                  <button
                    type="button"
                    className="child-list__item"
                    onClick={() => onSelect(child.id)}
                  >
                    <span>{child.label}</span>
                    <ChevronIcon size={15} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="node-panel__footer">
          Every node is generated only from the uploaded PDF. Page numbers point back to the
          evidence.
        </div>
      </aside>
    </>
  );
}
