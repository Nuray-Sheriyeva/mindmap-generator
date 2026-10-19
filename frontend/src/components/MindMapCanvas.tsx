import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react';
import { useEffect, useMemo, type RefObject } from 'react';

import {
  buildLayout,
  type LayoutDirection,
  type MindMapFlowNode,
  type MindMapNodeData,
} from '../lib/layout';
import type { MindMapResult } from '../types/mindmap';
import { MindMapActionsContext } from './mindmap-context';
import { MindMapNodeComponent } from './MindMapNodeView';

const NODE_TYPES = { mind: MindMapNodeComponent } as unknown as NodeTypes;

interface MindMapCanvasProps {
  result: MindMapResult;
  collapsed: ReadonlySet<string>;
  direction: LayoutDirection;
  selectedId: string | null;
  fitSignal: number;
  flowRef: RefObject<HTMLDivElement>;
  onToggle: (id: string) => void;
  onSelect: (id: string | null) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

function Canvas({
  result,
  collapsed,
  direction,
  selectedId,
  fitSignal,
  flowRef,
  onToggle,
  onSelect,
  onExpandAll,
  onCollapseAll,
}: MindMapCanvasProps) {
  const layout = useMemo(
    () => buildLayout(result.mindmap, collapsed, direction),
    [result.mindmap, collapsed, direction],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<MindMapFlowNode>(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(layout.edges);
  const { fitView } = useReactFlow();

  useEffect(() => {
    setNodes(layout.nodes);
    setEdges(layout.edges);
  }, [layout, setEdges, setNodes]);

  useEffect(() => {
    setNodes((current) =>
      current.map((node) =>
        node.selected === (node.id === selectedId)
          ? node
          : { ...node, selected: node.id === selectedId },
      ),
    );
  }, [selectedId, setNodes]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fitView({ padding: 0.22, duration: 350 });
    }, 90);
    return () => window.clearTimeout(timer);
  }, [fitSignal, fitView, layout]);

  return (
    <div className="flow-wrap" ref={flowRef}>
      <MindMapActionsContext.Provider value={{ toggleNode: onToggle }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) => onSelect(node.id)}
          onPaneClick={() => onSelect(null)}
          minZoom={0.12}
          maxZoom={2.4}
          nodesConnectable={false}
          edgesFocusable={false}
          proOptions={{ hideAttribution: false }}
          aria-label="Mind map canvas"
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1.4}
            color="#c9d5e5"
          />
          <Controls showInteractive={false} position="bottom-right" />
          <MiniMap
            pannable
            zoomable
            position="top-right"
            maskColor="rgba(148, 163, 184, 0.12)"
            nodeStrokeWidth={2}
            nodeColor={(node: Node) => {
              const data = node.data as unknown as MindMapNodeData;
              return data.color ?? '#94a3b8';
            }}
          />
          <Panel position="bottom-left" className="flow-panel">
            <button
              type="button"
              className="flow-panel__button"
              onClick={() => void fitView({ padding: 0.22, duration: 400 })}
            >
              Fit view
            </button>
            <span className="flow-panel__divider" aria-hidden="true" />
            <button type="button" className="flow-panel__button" onClick={onExpandAll}>
              Expand all
            </button>
            <button type="button" className="flow-panel__button" onClick={onCollapseAll}>
              Collapse all
            </button>
          </Panel>
        </ReactFlow>
      </MindMapActionsContext.Provider>
    </div>
  );
}

export function MindMapCanvas(props: MindMapCanvasProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
