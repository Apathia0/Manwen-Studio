import { memo, useEffect, useMemo, useRef, type MouseEvent as ReactMouseEvent } from 'react';
import type { VideoCanvasNodeCatalogItem } from '../../api';
import { isMembershipEdge } from './containerGroup';
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

/** 智能连线预览：将新增（绿色虚线）/ 将移除（红色虚线）的连线，仅用于叠加显示，不是真实连线。 */
export interface GhostEdge { key: string; source: string; target: string; sourceHandle?: string; targetHandle?: string; kind: 'add' | 'remove' }

export interface CanvasConnectionLayerProps {
  ghostEdges?: GhostEdge[];
  nodes: CanvasSceneNode[];
  edges: CanvasSceneEdge[];
  catalog: VideoCanvasNodeCatalogItem[];
  connecting: ConnectionHandle | null;
  mouseWorld: Position;
  connectionTargetNodeId: string | null;
  selectedConnectionId: string | null;
  handlers: CanvasInteractionHandlers;
}

const EMPTY_GHOST_EDGES: GhostEdge[] = [];

/**
 * 连线很多时（几百条），面板里与连线无关的重渲染（批量生成进度、运行状态轮询等）不该重算所有路径：
 * 只在节点 / 连线 / 目录 / 选中 / 连线预览变化时才重渲染。事件处理器通过 ref 取最新值，不参与比较。
 */
function sameLayerProps(prev: CanvasConnectionLayerProps, next: CanvasConnectionLayerProps) {
  return prev.nodes === next.nodes && prev.edges === next.edges && prev.catalog === next.catalog
    && prev.connecting === next.connecting && prev.mouseWorld === next.mouseWorld
    && prev.connectionTargetNodeId === next.connectionTargetNodeId && prev.selectedConnectionId === next.selectedConnectionId
    && prev.ghostEdges === next.ghostEdges;
}

function CanvasConnectionLayer({ nodes, edges, catalog, connecting, mouseWorld, connectionTargetNodeId, selectedConnectionId, handlers, ghostEdges = EMPTY_GHOST_EDGES }: CanvasConnectionLayerProps) {
  const handlersRef = useRef(handlers);
  useEffect(() => { handlersRef.current = handlers; });
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const catalogByType = useMemo(() => new Map(catalog.map((item) => [item.type, item])), [catalog]);
  const targetNode = connecting && connectionTargetNodeId ? (nodeById.get(connectionTargetNodeId) ?? null) : null;
  const sourceNode = connecting ? (nodeById.get(connecting.nodeId) ?? null) : null;

  return (
    <svg className="absolute left-0 top-0" width="1" height="1" style={{ overflow: 'visible', pointerEvents: 'none' }}>
      {edges.map((edge) => {
        if (isMembershipEdge(edge, nodes)) return null; // 组内成员边不绘制
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
            onSelect={() => handlersRef.current.onConnectionClick(edge.id)}
            onContextMenu={(event) => handlersRef.current.onConnectionContextMenu(event, edge.id)}
          />
        );
      })}
      {ghostEdges.map((ghost) => {
        const fromNode = nodeById.get(ghost.source);
        const toNode = nodeById.get(ghost.target);
        if (!fromNode || !toNode) return null;
        const from = portAnchor(fromNode, catalogByType.get(fromNode.type), 'output', ghost.sourceHandle);
        const to = portAnchor(toNode, catalogByType.get(toNode.type), 'input', ghost.targetHandle);
        const curvature = Math.max(Math.abs(to.x - from.x) * 0.5, CURVATURE_MIN);
        const color = ghost.kind === 'add' ? '#34d399' : '#f87171';
        return <path key={`ghost-${ghost.kind}-${ghost.key}`} d={`M ${from.x} ${from.y} C ${from.x + curvature} ${from.y}, ${to.x - curvature} ${to.y}, ${to.x} ${to.y}`} stroke={color} strokeWidth="3" strokeDasharray="8,6" fill="none" style={{ pointerEvents: 'none', filter: `drop-shadow(0 0 6px ${color}88)` }} />;
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

export default memo(CanvasConnectionLayer, sameLayerProps);
