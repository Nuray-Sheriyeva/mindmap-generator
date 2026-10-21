import { Handle, Position, type NodeProps } from '@xyflow/react';
import { memo, useContext, type CSSProperties } from 'react';

import type { MindMapFlowNode } from '../lib/layout';
import { formatPages } from '../lib/tree';
import { MindMapActionsContext } from './mindmap-context';

function MindMapNodeView({ data }: NodeProps<MindMapFlowNode>) {
  const { node, kind, depth, color, collapsed, hasChildren, childCount, direction } = data;
  const actions = useContext(MindMapActionsContext);
  const pages = formatPages(node.source_pages);
  const isRoot = depth === 0;
  const style = { '--node-color': color } as CSSProperties;

  return (
    <div
      className={[
        'mind-node',
        `mind-node--${kind}`,
        isRoot ? 'mind-node--root' : '',
        collapsed ? 'is-collapsed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={style}
    >
      {direction === 'LR' ? (
        <>
          <Handle type="target" position={Position.Left} className="mind-handle" />
          <Handle type="source" position={Position.Right} className="mind-handle" />
        </>
      ) : (
        <>
          <Handle type="target" position={Position.Top} className="mind-handle" />
          <Handle type="source" position={Position.Bottom} className="mind-handle" />
        </>
      )}

      {kind === 'leaf' ? (
        <div className="mind-leaf">
          <div className="mind-leaf__label">{node.label}</div>
          <p className="mind-leaf__explanation">{node.explanation}</p>
          {pages ? <span className="mind-leaf__pages">p. {pages}</span> : null}
        </div>
      ) : (
        <div className="mind-branch">
          <span className="mind-branch__dot" aria-hidden="true" />
          <span className="mind-branch__label">{node.label}</span>
          {hasChildren ? (
            <button
              type="button"
              className="mind-branch__toggle nodrag nopan"
              aria-label={
                collapsed
                  ? `Expand ${node.label} (${childCount} branches)`
                  : `Collapse ${node.label}`
              }
              onClick={(event) => {
                event.stopPropagation();
                actions?.toggleNode(node.id);
              }}
            >
              <span aria-hidden="true">{collapsed ? '▸' : '▾'}</span>
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

export const MindMapNodeComponent = memo(MindMapNodeView);
