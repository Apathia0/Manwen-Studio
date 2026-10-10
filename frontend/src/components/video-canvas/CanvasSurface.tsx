import { useCallback, useEffect, useRef, type DragEvent as ReactDragEvent, type MouseEvent as ReactMouseEvent, type MutableRefObject, type ReactNode, type RefObject } from 'react';
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

/** 手势结束后多久把视口提交回 React 状态（期间只直接改 DOM，不触发整棵画布重渲染） */
const VIEWPORT_COMMIT_DELAY_MS = 120;

/** 画布视口的命令式接口：平移 / 缩放手势直接改 DOM，停手后才提交到 React 状态 */
export interface CanvasSurfaceViewportApi {
  /** 立即应用视口（只改 DOM），并在停手后提交给 onViewportChange */
  setViewport: (next: CanvasViewport) => void;
  /** 读取当前最新视口（含尚未提交的手势中间值） */
  getViewport: () => CanvasViewport;
}

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
  /** 视口变化回调（手势停止后提交；手势进行中不会逐帧调用） */
  onViewportChange: (next: CanvasViewport) => void;
  /** 命令式视口接口（供平移手势等绕过 React 逐帧渲染） */
  viewportApiRef?: MutableRefObject<CanvasSurfaceViewportApi | null>;
  /** 文件拖放回调（world 为画布世界坐标） */
  onDrop?: (event: ReactDragEvent<HTMLDivElement>, world: { x: number; y: number }) => void;
  /** 画布内容（连线层 + 节点层） */
  children: ReactNode;
}

/** 背景网格样式：随视口平移 / 缩放（lines 网格线 / dots 点阵） */
function gridStyle(viewport: CanvasViewport, mode: CanvasBackgroundMode) {
  const gridSize = GRID_SIZE * viewport.scale;
  const x = viewport.x % gridSize;
  const y = viewport.y % gridSize;
  const dotSize = viewport.scale < 0.12 ? 0.8 : 1.15;
  const backgroundImage =
    mode === 'dots'
      ? `radial-gradient(circle, #34373d ${dotSize}px, transparent ${dotSize + 0.2}px)`
      : 'linear-gradient(#333333 1px, transparent 1px), linear-gradient(90deg, #333333 1px, transparent 1px)';
  return { backgroundImage, backgroundSize: `${gridSize}px ${gridSize}px`, backgroundPosition: `${x}px ${y}px` };
}

const worldTransform = (viewport: CanvasViewport) => `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`;

export default function CanvasSurface({ containerRef, viewport, tool, backgroundMode = 'lines', handlers, state, onViewportChange, viewportApiRef, onDrop, children }: CanvasSurfaceProps) {
  const worldRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  // 手势中的“实时视口”：缩放 / 平移每个事件都只更新它并直接改 DOM，停手后才提交，避免连线多时整棵画布逐帧重渲染
  const liveRef = useRef<CanvasViewport>(viewport);
  const commitTimerRef = useRef<number | null>(null);
  const onViewportChangeRef = useRef(onViewportChange);
  const modeRef = useRef(backgroundMode);
  useEffect(() => { onViewportChangeRef.current = onViewportChange; modeRef.current = backgroundMode; });

  const setLiveViewport = useCallback((next: CanvasViewport) => {
    liveRef.current = next;
    const world = worldRef.current;
    if (world) {
      world.style.transform = worldTransform(next);
      // 手势期间让浏览器把整层当作位图缩放（不逐帧重新栅格化大量连线 / 节点），停手提交时再清晰重绘
      world.style.willChange = 'transform';
    }
    const grid = gridRef.current;
    if (grid) Object.assign(grid.style, gridStyle(next, modeRef.current));
    if (commitTimerRef.current !== null) window.clearTimeout(commitTimerRef.current);
    commitTimerRef.current = window.setTimeout(() => {
      commitTimerRef.current = null;
      if (worldRef.current) worldRef.current.style.willChange = '';
      onViewportChangeRef.current(liveRef.current);
    }, VIEWPORT_COMMIT_DELAY_MS);
  }, []);

  useEffect(() => {
    if (!viewportApiRef) return undefined;
    viewportApiRef.current = { setViewport: setLiveViewport, getViewport: () => liveRef.current };
    return () => { viewportApiRef.current = null; };
  }, [setLiveViewport, viewportApiRef]);

  // 外部改动视口（工具栏缩放、适应画面动画、撤销等）时同步实时视口；手势尚未提交时以手势为准
  useEffect(() => {
    if (commitTimerRef.current === null) liveRef.current = viewport;
  }, [viewport]);
  useEffect(() => () => { if (commitTimerRef.current !== null) window.clearTimeout(commitTimerRef.current); }, []);

  // 滚轮缩放（围绕鼠标位置）：必须用原生非被动监听才能 preventDefault，React 的 onWheel 是被动监听
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const handleWheel = (event: WheelEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-canvas-no-zoom],.ant-modal,.ant-popover,.ant-dropdown,.ant-select-dropdown,.ant-picker-dropdown')) return;
      event.preventDefault();
      const current = liveRef.current;
      const factor = Math.pow(1.1, -event.deltaY / 100);
      const newScale = Math.min(Math.max(current.scale * factor, MIN_SCALE), MAX_SCALE);
      const rect = container.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      const worldX = (mouseX - current.x) / current.scale;
      const worldY = (mouseY - current.y) / current.scale;
      setLiveViewport({ x: mouseX - worldX * newScale, y: mouseY - worldY * newScale, scale: newScale });
    };
    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, [containerRef, setLiveViewport]);

  const handleDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!onDrop) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const current = liveRef.current;
    onDrop(event, { x: (event.clientX - rect.left - current.x) / current.scale, y: (event.clientY - rect.top - current.y) / current.scale });
  };

  const cursor = state.isPanning ? 'grabbing' : tool === 'pan' ? 'grab' : 'default';

  return (
    <div
      ref={containerRef}
      role="application"
      aria-label="无限画布"
      className="relative h-full w-full select-none overflow-hidden bg-[#181818] outline-none"
      style={{ cursor }}
      onPointerDownCapture={(event) => {
        const target = event.target as HTMLElement | null;
        const isEditable = Boolean(target?.closest('input, textarea, select, [contenteditable="true"]'));
        const shouldPan = event.button === 1 || (event.button === 0 && (tool === 'pan' || event.ctrlKey || state.isSpacePressed));
        if (shouldPan && !isEditable) {
          event.stopPropagation();
          handlers.onCanvasMouseDown(event);
        }
      }}
      onPointerDown={handlers.onCanvasMouseDown}
      onDoubleClick={handlers.onCanvasDoubleClick as unknown as (event: ReactMouseEvent<HTMLDivElement>) => void}
      onContextMenu={handlers.onContextMenu as unknown as (event: ReactMouseEvent) => void}
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
    >
      {backgroundMode === 'blank' ? null : <div ref={gridRef} aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-40" style={gridStyle(viewport, backgroundMode)} />}
      <div ref={worldRef} className="absolute origin-top-left" style={{ transform: worldTransform(viewport) }}>
        {children}
      </div>
    </div>
  );
}
