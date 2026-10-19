import { Handle, Position, type NodeProps } from '@xyflow/react';
import { memo, useContext, type CSSProperties } from 'react';

import type { MindMapFlowNode } from '../lib/layout';
import { formatPages } from '../lib/tree';
import { MindMapActionsContext } from './mindmap-context';

function MindMapNodeView({ data, selected }: NodeProps<MindMapFlowNode>) {
  const { node, depth, color, collapsed, hasChildren, childCount, direction } = data;
  const actions = useContext(MindMapActionsContext);
  const pages = formatPages(node.source_pages);
  const isRoot = depth === 0;

  const style = { '--node-color': color } as CSSProperties;

  return (
    <div
      className={[
        'mind-node',
        isRoot ? 'mind-node--root' : '',
        selected ? 'is-selected' : '',
        collapsed ? 'is-collapsed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={style}
      title={node.summary || node.label}
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

      <div className="mind-node__body">
        <div className="mind-node__top">
          <span className="mind-node__label">{node.label}</span>
          {hasChildren && (
            <button
              type="button"
              className="mind-node__toggle"
              aria-label={
                collapsed ? `Expand ${node.label}` : `Collapse ${node.label}`
              }
              title={collapsed ? 'Expand branch' : 'Collapse branch'}
              onClick={(event) => {
                event.stopPropagation();
                actions?.toggleNode(node.id);
              }}
            >
              {collapsed ? `+${childCount}` : '−'}
            </button>
          )}
        </div>
        <div className="mind-node__meta">
          {pages ? <span className="mind-node__pages">p. {pages}</span> : null}
          {hasChildren ? (
            <span className="mind-node__count">
              {childCount} {childCount === 1 ? 'branch' : 'branches'}
            </span>
          ) : (
            <span className="mind-node__leaf">detail</span>
          )}
        </div>
      </div>
    </div>
  );
}

export const MindMapNodeComponent = memo(MindMapNodeView);
