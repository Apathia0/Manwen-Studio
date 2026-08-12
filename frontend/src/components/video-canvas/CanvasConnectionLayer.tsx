import { useMemo, type MouseEvent as ReactMouseEvent } from 'react';
import type { VideoCanvasNodeCatalogItem } from '../../api';
import { nodeSize, portY, type CanvasInteractionHandlers, type CanvasSceneEdge, type CanvasSceneNode, type ConnectionHandle, type Position } from './useCanvasInteractions';

/**
 * 画布连线层（SVG）。
 *
 * 移植自 MIT 参考项目 infinite-canvas 的 canvas-connections 组件：
 * - 贝塞尔曲线（曲率 max(|dx|*0.5, 56)）
 * - 16px 透明热区用于点击选中 / 右键菜单
 * - 连线进行中渲染虚线预览，吸附到目标节点时端点吸附
 * 端点按 handleKey 定位到对应端口（多端口 portY 均分）。
 */

const SELECTION_BLUE = '#2f80ff';
const EDGE_COLOR = '#6b7280';
const CURVATURE_MIN = 56;

/** 端口锚点（世界坐标）：input 在节点左侧，output 在节点右侧 */
function portAnchor(node: CanvasSceneNode, catalogItem: VideoCanvasNodeCatalogItem | undefined, side: 'input' | 'output', handleKey: string | null | undefined): Position {
  const size = nodeSize(node);
  const ports = side === 'input' ? (catalogItem?.inputs ?? []) : (catalogItem?.outputs ?? []);
  const index = handleKey ? Math.max(0, ports.findIndex((port) => port.key === handleKey)) : 0;
  const y = node.position.y + portY(index, ports.length, size.height);
  return side === 'input' ? { x: node.position.x, y } : { x: node.position.x + size.width, y };
}

function ConnectionPath({ edge, from, to, active, onSelect, onContextMenu }: {
  edge: CanvasSceneEdge;
  from: Position;
  to: Position;
  active: boolean;
  onSelect: () => void;
  onContextMenu?: (event: ReactMouseEvent<SVGPathElement>) => void;
}) {
  const dx = Math.abs(to.x - from.x);
  const curvature = Math.max(dx * 0.5, CURVATURE_MIN);
  const pathD = `M ${from.x} ${from.y} C ${from.x + curvature} ${from.y}, ${to.x - curvature} ${to.y}, ${to.x} ${to.y}`;
  return (
    <g>
      <path
        data-connection-id={edge.id}
        d={pathD}
        stroke="transparent"
        strokeWidth="16"
        fill="none"
        style={{ cursor: 'pointer', pointerEvents: 'stroke' }}
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onContextMenu?.(event);
        }}
      />
      <path
        d={pathD}
        stroke={active ? SELECTION_BLUE : EDGE_COLOR}
        strokeWidth={active ? 3 : 2}
        strokeOpacity={active ? 1 : 0.82}
        fill="none"
        style={{ filter: active ? `drop-shadow(0 0 8px ${SELECTION_BLUE}66)` : undefined, pointerEvents: 'none' }}
      />
    </g>
  );
}

function ActiveConnectionPath({ connecting, sourceNode, sourceCatalogItem, mouseWorld, targetNode, targetCatalogItem }: {
  connecting: ConnectionHandle;
  sourceNode: CanvasSceneNode;
  sourceCatalogItem: VideoCanvasNodeCatalogItem | undefined;
  mouseWorld: Position;
  targetNode: CanvasSceneNode | null;
  targetCatalogItem: VideoCanvasNodeCatalogItem | undefined;
}) {
  const sourceAnchor = connecting.handleType === 'source'
    ? portAnchor(sourceNode, sourceCatalogItem, 'output', connecting.handleKey)
    : portAnchor(sourceNode, sourceCatalogItem, 'input', connecting.handleKey);
  const start = connecting.handleType === 'source' ? sourceAnchor : mouseWorld;
  const end = connecting.handleType === 'source' ? mouseWorld : sourceAnchor;
  const snappedStart = connecting.handleType === 'target' && targetNode ? portAnchor(targetNode, targetCatalogItem, 'output', null) : start;
  const snappedEnd = connecting.handleType === 'source' && targetNode ? portAnchor(targetNode, targetCatalogItem, 'input', null) : end;
  const distance = Math.abs(snappedEnd.x - snappedStart.x);
  const pathD = `M ${snappedStart.x} ${snappedStart.y} C ${snappedStart.x + distance * 0.5} ${snappedStart.y}, ${snappedEnd.x - distance * 0.5} ${snappedEnd.y}, ${snappedEnd.x} ${snappedEnd.y}`;
  return <path d={pathD} stroke={SELECTION_BLUE} strokeWidth="2" fill="none" strokeDasharray="5,5" />;
}

export interface CanvasConnectionLayerProps {
  nodes: CanvasSceneNode[];
  edges: CanvasSceneEdge[];
  catalog: VideoCanvasNodeCatalogItem[];
  connecting: ConnectionHandle | null;
  mouseWorld: Position;
  connectionTargetNodeId: string | null;
  selectedConnectionId: string | null;
  handlers: CanvasInteractionHandlers;
}

export default function CanvasConnectionLayer({ nodes, edges, catalog, connecting, mouseWorld, connectionTargetNodeId, selectedConnectionId, handlers }: CanvasConnectionLayerProps) {
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const catalogByType = useMemo(() => new Map(catalog.map((item) => [item.type, item])), [catalog]);
  const targetNode = connecting && connectionTargetNodeId ? (nodeById.get(connectionTargetNodeId) ?? null) : null;
  const sourceNode = connecting ? (nodeById.get(connecting.nodeId) ?? null) : null;

  return (
    <svg className="absolute left-0 top-0" width="1" height="1" style={{ overflow: 'visible', pointerEvents: 'none' }}>
      {edges.map((edge) => {
        const fromNode = nodeById.get(edge.source);
        const toNode = nodeById.get(edge.target);
        if (!fromNode || !toNode) return null;
        const from = portAnchor(fromNode, catalogByType.get(fromNode.type), 'output', edge.sourceHandle);
        const to = portAnchor(toNode, catalogByType.get(toNode.type), 'input', edge.targetHandle);
        return (
          <ConnectionPath
            key={edge.id}
            edge={edge}
            from={from}
            to={to}
            active={selectedConnectionId === edge.id}
            onSelect={() => handlers.onConnectionClick(edge.id)}
            onContextMenu={(event) => handlers.onConnectionContextMenu(event, edge.id)}
          />
        );
      })}
      {connecting && sourceNode ? (
        <ActiveConnectionPath
          connecting={connecting}
          sourceNode={sourceNode}
          sourceCatalogItem={catalogByType.get(sourceNode.type)}
          mouseWorld={mouseWorld}
          targetNode={targetNode}
          targetCatalogItem={targetNode ? catalogByType.get(targetNode.type) : undefined}
        />
      ) : null}
    </svg>
  );
}