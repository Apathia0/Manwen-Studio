import type { DragEvent as ReactDragEvent, MouseEvent as ReactMouseEvent, ReactNode, RefObject, WheelEvent as ReactWheelEvent } from 'react';
import { GRID_SIZE, MAX_SCALE, MIN_SCALE, type CanvasInteractionHandlers, type CanvasInteractionState, type CanvasTool, type CanvasViewport } from './useCanvasInteractions';

/**
 * 画布视口容器。
 *
 * 移植自 MIT 参考项目 infinite-canvas 的 InfiniteCanvas 组件：
 * - DOM transform 视口变换（translate + scale）
 * - 滚轮围绕鼠标位置缩放（0.05x - 5x）
 * - 点阵 / 网格背景（随视口平移）
 * - 文件拖放导入（world 坐标换算后交给集成方）
 * 交互处理（框选 / 平移 / 连线 / 右键）全部委托给 useCanvasInteractions 的 handlers 与 state。
 */

export type CanvasBackgroundMode = 'lines' | 'dots' | 'blank';

export interface CanvasSurfaceProps {
  /** 画布容器 ref（由集成方持有，用于坐标换算与尺寸测量） */
  containerRef: RefObject<HTMLDivElement | null>;
  /** 当前视口变换 */
  viewport: CanvasViewport;
  /** 当前工具（由 useCanvasInteractions 计算出的生效工具） */
  tool: CanvasTool;
  /** 背景网格模式（默认 lines 网格线） */
  backgroundMode?: CanvasBackgroundMode;
  /** 交互处理器（来自 useCanvasInteractions） */
  handlers: CanvasInteractionHandlers;
  /** 交互状态（来自 useCanvasInteractions） */
  state: CanvasInteractionState;
  /** 视口变化回调（缩放） */
  onViewportChange: (next: CanvasViewport) => void;
  /** 文件拖放回调（world 为画布世界坐标） */
  onDrop?: (event: ReactDragEvent<HTMLDivElement>, world: { x: number; y: number }) => void;
  /** 画布内容（连线层 + 节点层） */
  children: ReactNode;
}

/** 背景网格层：lines 网格线 / dots 点阵，随视口平移，pointer-events 穿透 */
function CanvasGrid({ viewport, mode }: { viewport: CanvasViewport; mode: CanvasBackgroundMode }) {
  if (mode === 'blank') return null;
  const gridSize = GRID_SIZE * viewport.scale;
  const x = viewport.x % gridSize;
  const y = viewport.y % gridSize;
  const dotSize = viewport.scale < 0.12 ? 0.8 : 1.15;
  const backgroundImage =
    mode === 'dots'
      ? `radial-gradient(circle, #34373d ${dotSize}px, transparent ${dotSize + 0.2}px)`
      : 'linear-gradient(#333333 1px, transparent 1px), linear-gradient(90deg, #333333 1px, transparent 1px)';
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 opacity-40"
      style={{ backgroundImage, backgroundSize: `${gridSize}px ${gridSize}px`, backgroundPosition: `${x}px ${y}px` }}
    />
  );
}

export default function CanvasSurface({ containerRef, viewport, tool, backgroundMode = 'lines', handlers, state, onViewportChange, onDrop, children }: CanvasSurfaceProps) {
  const handleWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest('[data-canvas-no-zoom],.ant-modal,.ant-popover,.ant-dropdown,.ant-select-dropdown,.ant-picker-dropdown')) return;
    event.preventDefault();
    const delta = -event.deltaY;
    const factor = Math.pow(1.1, delta / 100);
    const newScale = Math.min(Math.max(viewport.scale * factor, MIN_SCALE), MAX_SCALE);
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;
    const worldX = (mouseX - viewport.x) / viewport.scale;
    const worldY = (mouseY - viewport.y) / viewport.scale;
    onViewportChange({ x: mouseX - worldX * newScale, y: mouseY - worldY * newScale, scale: newScale });
  };

  const handleDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!onDrop) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    onDrop(event, { x: (event.clientX - rect.left - viewport.x) / viewport.scale, y: (event.clientY - rect.top - viewport.y) / viewport.scale });
  };

  const cursor = state.isPanning ? 'grabbing' : tool === 'pan' ? 'grab' : 'default';

  return (
    <div
      ref={containerRef}
      role="application"
      aria-label="无限画布"
      className="relative h-full w-full select-none overflow-hidden bg-[#181818] outline-none"
      style={{ cursor }}
      onPointerDown={handlers.onCanvasMouseDown}
      onDoubleClick={handlers.onCanvasDoubleClick as unknown as (event: ReactMouseEvent<HTMLDivElement>) => void}
      onWheel={handleWheel}
      onContextMenu={handlers.onContextMenu as unknown as (event: ReactMouseEvent) => void}
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
    >
      <CanvasGrid viewport={viewport} mode={backgroundMode} />
      <div className="absolute origin-top-left" style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})` }}>
        {children}
      </div>
    </div>
  );
}
