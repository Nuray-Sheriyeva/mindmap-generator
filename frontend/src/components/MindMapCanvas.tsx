import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  getNodesBounds,
  getViewportForBounds,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react';
import { useEffect, useMemo, useRef, type MutableRefObject } from 'react';

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

export interface FlowExportApi {
  exportImage: (format: 'png' | 'svg') => Promise<void>;
}

interface MindMapCanvasProps {
  result: MindMapResult;
  collapsed: ReadonlySet<string>;
  direction: LayoutDirection;
  fitSignal: number;
  exportRef: MutableRefObject<FlowExportApi | null>;
  onToggle: (id: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

function Canvas({
  result,
  collapsed,
  direction,
  fitSignal,
  exportRef,
  onToggle,
  onExpandAll,
  onCollapseAll,
}: MindMapCanvasProps) {
  const layout = useMemo(
    () => buildLayout(result.mindmap, collapsed, direction),
    [result.mindmap, collapsed, direction],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<MindMapFlowNode>(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(layout.edges);
  const { fitView, setViewport } = useReactFlow();
  const flowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setNodes(layout.nodes);
    setEdges(layout.edges);
  }, [layout, setEdges, setNodes]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const wrapper = flowRef.current;
      const root = layout.nodes.find((node) => node.id === result.mindmap.id);
      if (!wrapper || !root) return;
      const rect = wrapper.getBoundingClientRect();
      const rootWidth = Number((root.style as { width?: number })?.width ?? 260);
      const rootHeight = Number((root.style as { height?: number })?.height ?? 74);
      const zoom = direction === 'LR' ? 0.82 : 0.78;
      const anchorX =
        direction === 'LR'
          ? Math.max(rect.width * 0.24, (rootWidth * zoom) / 2 + 16)
          : rect.width / 2;
      const anchorY =
        direction === 'LR'
          ? rect.height / 2
          : Math.max(rect.height * 0.22, (rootHeight * zoom) / 2 + 16);
      void setViewport(
        {
          x: anchorX - (root.position.x + rootWidth / 2) * zoom,
          y: anchorY - (root.position.y + rootHeight / 2) * zoom,
          zoom,
        },
        { duration: 300 },
      );
    }, 120);
    return () => window.clearTimeout(timer);
  }, [direction, layout.nodes, result.mindmap.id, setViewport]);

  useEffect(() => {
    if (fitSignal <= 0) return;
    const timer = window.setTimeout(() => {
      void fitView({ padding: 0.12, duration: 400 });
    }, 30);
    return () => window.clearTimeout(timer);
  }, [fitSignal, fitView]);

  useEffect(() => {
    exportRef.current = {
      exportImage: async (format: 'png' | 'svg') => {
        const viewportElement = flowRef.current?.querySelector<HTMLElement>(
          '.react-flow__viewport',
        );
        if (!viewportElement || nodes.length === 0) {
          throw new Error('The canvas is not ready yet.');
        }
        const { toPng, toSvg } = await import('html-to-image');
        const bounds = getNodesBounds(nodes);
        const maxDimension = 5600;
        const scale = Math.min(
          maxDimension / Math.max(bounds.width, 1),
          maxDimension / Math.max(bounds.height, 1),
          1.35,
        );
        const width = Math.max(1800, Math.round(bounds.width * scale));
        const height = Math.max(1100, Math.round(bounds.height * scale));
        const viewport = getViewportForBounds(bounds, width, height, 0.1, 2, 0.06);
        const options = {
          backgroundColor: '#f7f7fb',
          width,
          height,
          pixelRatio: 1.5,
          cacheBust: true,
          style: {
            width: `${width}px`,
            height: `${height}px`,
            transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
          },
        };
        const dataUrl =
          format === 'png'
            ? await toPng(viewportElement, options)
            : await toSvg(viewportElement, options);
        const anchor = document.createElement('a');
        anchor.href = dataUrl;
        anchor.download = `${result.document.filename.replace(/\.pdf$/i, '') || 'document'}-mindmap.${format}`;
        anchor.click();
      },
    };
    return () => {
      exportRef.current = null;
    };
  }, [exportRef, nodes, result.document.filename]);

  return (
    <div className="flow-wrap" ref={flowRef}>
      <MindMapActionsContext.Provider value={{ toggleNode: onToggle }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          minZoom={0.08}
          maxZoom={2.4}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: false }}
          aria-label="Mind map canvas"
        >
          <Background
            variant={BackgroundVariant.Lines}
            gap={28}
            size={1}
            color="#dedee9"
          />
          <Controls showInteractive={false} position="bottom-right" />
          <MiniMap
            pannable
            zoomable
            position="top-right"
            maskColor="rgba(10, 10, 18, 0.08)"
            nodeStrokeWidth={2}
            nodeColor={(node: Node) => {
              const data = node.data as unknown as MindMapNodeData;
              return data.color ?? '#7c5cff';
            }}
          />
          <Panel position="bottom-left" className="flow-panel">
            <button
              type="button"
              className="flow-panel__button"
              onClick={() => void fitView({ padding: 0.12, duration: 400 })}
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
