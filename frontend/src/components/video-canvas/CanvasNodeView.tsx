import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import type { VideoCanvasNodeCatalogItem, VideoCanvasPort } from '../../api';
import { nodeSize, portY, type CanvasInteractionHandlers, type CanvasSceneNode, type ConnectionHandle } from './useCanvasInteractions';
import SceneListNodeView from './SceneListNodeView';
import ContainerNodeView, { type ContainerNodeConfig } from './ContainerNodeView';

/**
 * 画布节点视图。
 *
 * 移植自 MIT 参考项目 infinite-canvas 的 CanvasNode 组件：
 * - 深色卡片 + 选中/悬停蓝色描边（#2f80ff）
 * - 四角缩放热区（图片/视频节点保持宽高比，最小 220x160）
 * - 左右端口圆点（多端口按 portY 均分，handleKey 绑定连线）
 * 拖拽 / 连线 / 右键交互委托给 useCanvasInteractions 的 handlers。
 */

const SELECTION_BLUE = '#2f80ff';
const NODE_BG = '#202226';
const NODE_BORDER = '#3a3f45';
const PORT_BORDER = '#6b7280';
const MIN_WIDTH = 220;
const MIN_HEIGHT = 160;
/** 保持宽高比的节点类型（图片 / 视频类） */
const RATIO_LOCKED_TYPES = new Set(['image', 'video', 'image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset']);

type ResizeCorner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

interface ResizeState {
  isResizing: boolean;
  corner: ResizeCorner;
  startX: number;
  startY: number;
  startLeft: number;
  startTop: number;
  startWidth: number;
  startHeight: number;
  keepRatio: boolean;
  ratio: number;
}

export interface CanvasNodeViewProps {
  node: CanvasSceneNode;
  catalogItem: VideoCanvasNodeCatalogItem;
  selected: boolean;
  connecting: ConnectionHandle | null;
  connectionTargetNodeId: string | null;
  scale: number;
  handlers: CanvasInteractionHandlers;
  onResize: (nodeId: string, width: number, height: number, position: { x: number; y: number }) => void;
  onResizeEnd: (nodeId: string) => void;
  onNodeContextMenu?: (event: ReactMouseEvent, nodeId: string) => void;
  renderContent?: (node: CanvasSceneNode) => ReactNode;
}

function ResizeHandle({ corner, onMouseDown }: { corner: ResizeCorner; onMouseDown: (event: ReactMouseEvent, corner: ResizeCorner) => void }) {
  const positionClass = {
    'top-left': '-left-[14px] -top-[14px] cursor-nwse-resize',
    'top-right': '-right-[14px] -top-[14px] cursor-nesw-resize',
    'bottom-left': '-bottom-[14px] -left-[14px] cursor-nesw-resize',
    'bottom-right': '-bottom-[14px] -right-[14px] cursor-nwse-resize',
  }[corner];
  return (
    <div
      className={`absolute z-50 size-7 ${positionClass}`}
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => onMouseDown(event, corner)}
    />
  );
}

function PortList({ side, ports, node, height, visible, highlighted, handlers }: {
  side: 'left' | 'right';
  ports: VideoCanvasPort[];
  node: CanvasSceneNode;
  height: number;
  visible: boolean;
  highlighted: boolean;
  handlers: CanvasInteractionHandlers;
}) {
  const handleType = side === 'left' ? 'target' : 'source';
  return (
    <>
      {ports.map((port, index) => (
        <div
          key={port.key}
          className={`absolute z-30 flex size-12 -translate-y-1/2 cursor-crosshair items-center justify-center transition-opacity duration-150 ${side === 'left' ? '-left-6' : '-right-6'} ${visible ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'}`}
          style={{ top: portY(index, ports.length, height) }}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => handlers.onNodeConnectStart(event, node.id, handleType, port.key)}
        >
          <div
            className="size-3 rounded-full border-2 transition-all hover:scale-125"
            style={{ background: NODE_BG, borderColor: highlighted ? SELECTION_BLUE : PORT_BORDER }}
          />
        </div>
      ))}
    </>
  );
}

export default function CanvasNodeView({ node, catalogItem, selected, connecting, connectionTargetNodeId, scale, handlers, onResize, onResizeEnd, onNodeContextMenu, renderContent }: CanvasNodeViewProps) {
  const [hovered, setHovered] = useState(false);
  const resizeRef = useRef<ResizeState>({ isResizing: false, corner: 'bottom-right', startX: 0, startY: 0, startLeft: 0, startTop: 0, startWidth: 0, startHeight: 0, keepRatio: false, ratio: 1 });
  const size = nodeSize(node);
  const isConnecting = connecting !== null;
  const isConnectionTarget = connectionTargetNodeId === node.id;
  const isActive = selected || hovered;
  const resizeUpRef = useRef<((event: MouseEvent) => void) | null>(null);

  const handleResizeMove = useCallback((event: MouseEvent) => {
    if (!resizeRef.current.isResizing) return;
    const state = resizeRef.current;
    const dx = (event.clientX - state.startX) / scale;
    const dy = (event.clientY - state.startY) / scale;
    const startRight = state.startLeft + state.startWidth;
    const startBottom = state.startTop + state.startHeight;
    const fromLeft = state.corner.includes('left');
    const fromTop = state.corner.includes('top');
    const rawWidth = Math.max(MIN_WIDTH, state.startWidth + (fromLeft ? -dx : dx));
    const rawHeight = Math.max(MIN_HEIGHT, state.startHeight + (fromTop ? -dy : dy));
    let width = rawWidth;
    let height = rawHeight;
    if (state.keepRatio) {
      const ratio = state.ratio;
      if (Math.abs(dx) >= Math.abs(dy)) {
        height = width / ratio;
      } else {
        width = height * ratio;
      }
      if (height < MIN_HEIGHT) {
        height = MIN_HEIGHT;
        width = height * ratio;
      }
      if (width < MIN_WIDTH) {
        width = MIN_WIDTH;
        height = width / ratio;
      }
    }
    onResize(node.id, width, height, {
      x: fromLeft ? startRight - width : state.startLeft,
      y: fromTop ? startBottom - height : state.startTop,
    });
  }, [node.id, onResize, scale]);

  const handleResizeUp = useCallback(() => {
    resizeRef.current.isResizing = false;
    window.removeEventListener('mousemove', handleResizeMove);
    const resizeUp = resizeUpRef.current;
    if (resizeUp) window.removeEventListener('mouseup', resizeUp);
    onResizeEnd(node.id);
  }, [handleResizeMove, node.id, onResizeEnd]);

  useEffect(() => {
    resizeUpRef.current = handleResizeUp;
    return () => {
      if (resizeUpRef.current === handleResizeUp) resizeUpRef.current = null;
    };
  }, [handleResizeUp]);

  const handleResizeMouseDown = (event: ReactMouseEvent, corner: ResizeCorner) => {
    event.stopPropagation();
    event.preventDefault();
    handlers.onNodeResizeStart(node.id);
    resizeRef.current = {
      isResizing: true,
      corner,
      startX: event.clientX,
      startY: event.clientY,
      startLeft: node.position.x,
      startTop: node.position.y,
      startWidth: size.width,
      startHeight: size.height,
      keepRatio: RATIO_LOCKED_TYPES.has(node.type),
      ratio: size.width / (size.height || 1),
    };
    window.addEventListener('mousemove', handleResizeMove);
    window.addEventListener('mouseup', handleResizeUp);
  };

  useEffect(() => {
    return () => {
      window.removeEventListener('mousemove', handleResizeMove);
      window.removeEventListener('mouseup', handleResizeUp);
    };
  }, [handleResizeMove, handleResizeUp]);

  const handleNodeContextMenu = (event: ReactMouseEvent) => {
    if (onNodeContextMenu) {
      onNodeContextMenu(event, node.id);
      return;
    }
    event.preventDefault();
    event.stopPropagation();
  };

  const isGroupFrame = node.type === 'container' || node.data.config?.node_role === 'container';

  const ports = (
    <>
      {catalogItem.inputs.length > 0 ? (
        <PortList side="left" ports={catalogItem.inputs} node={node} height={size.height} visible={isActive || isConnecting} highlighted={isConnecting && isConnectionTarget} handlers={handlers} />
      ) : null}
      {catalogItem.outputs.length > 0 ? (
        <PortList side="right" ports={catalogItem.outputs} node={node} height={size.height} visible={isActive || isConnecting} highlighted={isConnecting && isConnectionTarget} handlers={handlers} />
      ) : null}
    </>
  );

  // 组框：无卡片实体，根元素 pointer-events-none（框内空白可拉框选/穿透），
  // 仅标题栏与端口可交互；固定 z-[5] 保证永远画在成员节点之下。
  if (isGroupFrame) {
    return (
      <div
        data-node-id={node.id}
        className="node-element absolute z-[5] select-none"
        style={{
          transform: `translate(${node.position.x}px, ${node.position.y}px)`,
          width: size.width,
          height: size.height,
          contain: 'layout style',
          pointerEvents: 'none',
        }}
        onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => handlers.onNodePointerDown(event, node.id)}
        onDragStart={(event) => event.preventDefault()}
        onContextMenu={handleNodeContextMenu}
      >
        <div
          className="absolute inset-0 rounded-3xl border-2 transition-colors"
          style={{
            borderColor: selected ? SELECTION_BLUE : 'rgba(47,128,255,.4)',
            background: selected ? 'rgba(47,128,255,.06)' : 'rgba(255,255,255,.02)',
            boxShadow: selected ? `0 0 0 1px ${SELECTION_BLUE}55` : undefined,
          }}
        />
        <div className="absolute inset-x-0 top-0">
          {renderContent ? renderContent(node) : (
            <ContainerNodeView config={(node.data.config || {}) as unknown as ContainerNodeConfig} />
          )}
        </div>
        {ports}
      </div>
    );
  }

  return (
    <div
      data-node-id={node.id}
      className={`node-element absolute flex select-none flex-col transition-shadow duration-200 ${selected ? 'z-50' : 'z-10'}`}
      style={{
        transform: `translate(${node.position.x}px, ${node.position.y}px)`,
        width: size.width,
        height: size.height,
        contain: 'layout style',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => handlers.onNodePointerDown(event, node.id)}
      // 内容图片默认可被浏览器原生拖拽，原生拖拽会派发 pointercancel 打断画布自己的节点拖拽
      onDragStart={(event) => event.preventDefault()}
      onContextMenu={handleNodeContextMenu}
    >
      <div
        className="relative h-full w-full overflow-visible rounded-3xl border-2"
        style={{
          background: NODE_BG,
          borderColor: isActive ? SELECTION_BLUE : NODE_BORDER,
          boxShadow: isActive ? `0 0 0 1px ${SELECTION_BLUE}55` : undefined,
        }}
      >
        <div className="relative flex h-full w-full items-center justify-center overflow-hidden rounded-[22px]">
          {renderContent ? renderContent(node) : (
            node.type === 'scene' ? (
              <SceneListNodeView
                config={(node.data.config || {}) as any}
                onChange={() => {}}
              />
            ) : (
              <span className="px-3 text-center text-xs font-medium text-gray-300">{node.data.label || catalogItem.label}</span>
            )
          )}
        </div>
        <ResizeHandle corner="top-left" onMouseDown={handleResizeMouseDown} />
        <ResizeHandle corner="top-right" onMouseDown={handleResizeMouseDown} />
        <ResizeHandle corner="bottom-left" onMouseDown={handleResizeMouseDown} />
        <ResizeHandle corner="bottom-right" onMouseDown={handleResizeMouseDown} />
      </div>

      {ports}
    </div>
  );
}
