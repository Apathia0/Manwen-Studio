import { useCallback, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

/**
 * 画布小地图（240x160）。
 * 根据所有节点的世界坐标计算世界范围，将节点与视口矩形映射到小地图上；
 * 在小地图上点击 / 拖拽时反算世界坐标，通过 onViewportChange 回调导航视口。
 * 纯展示组件，不持有任何全局 store。
 */
export interface CanvasMiniMapNode {
  id: string;
  position: { x: number; y: number };
  width?: number;
  height?: number;
  type: string;
}

export interface CanvasMiniMapProps {
  /** 画布节点列表（只需 id / position / type，宽高可选） */
  nodes: CanvasMiniMapNode[];
  /** 当前视口：世界坐标偏移 + 缩放比例 */
  viewport: { x: number; y: number; scale: number };
  /** 视口尺寸（屏幕像素） */
  viewportSize: { width: number; height: number };
  /** 导航视口回调（x / y 为世界坐标偏移，scale 保持不变） */
  onViewportChange: (next: { x: number; y: number; scale: number }) => void;
}

/** 小地图固定尺寸 */
const MAP_WIDTH = 240;
const MAP_HEIGHT = 160;
/** 节点宽高缺失时的默认尺寸 */
const DEFAULT_NODE_WIDTH = 300;
const DEFAULT_NODE_HEIGHT = 200;
/** 节点边界外的留白（世界坐标） */
const WORLD_PADDING = 500;

/** 节点类型 → 小地图矩形颜色映射（仅 text/image/video 三种有专属色，其余默认灰） */
function nodeColor(type: string): string {
  if (type === 'text') return '#8b847e';
  if (type === 'image') return '#3b82f6';
  if (type === 'video') return '#a855f7';
  return '#6f6862';
}

export default function CanvasMiniMap({ nodes, viewport, viewportSize, onViewportChange }: CanvasMiniMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // 计算节点包围盒世界范围，并求出小地图映射的缩放与居中偏移
  const { worldBounds, scale, offset } = useMemo(() => {
    if (!nodes.length) {
      // 无节点时使用固定默认世界范围
      return { worldBounds: { x: -500, y: -500, w: 1000, h: 1000 }, scale: 0.16, offset: { x: 40, y: 0 } };
    }

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    nodes.forEach((node) => {
      const w = node.width ?? DEFAULT_NODE_WIDTH;
      const h = node.height ?? DEFAULT_NODE_HEIGHT;
      minX = Math.min(minX, node.position.x);
      minY = Math.min(minY, node.position.y);
      maxX = Math.max(maxX, node.position.x + w);
      maxY = Math.max(maxY, node.position.y + h);
    });

    minX -= WORLD_PADDING;
    minY -= WORLD_PADDING;
    maxX += WORLD_PADDING;
    maxY += WORLD_PADDING;

    const boundsWidth = maxX - minX;
    const boundsHeight = maxY - minY;
    const nextScale = Math.min(MAP_WIDTH / boundsWidth, MAP_HEIGHT / boundsHeight);
    const mapContentW = boundsWidth * nextScale;
    const mapContentH = boundsHeight * nextScale;

    return {
      worldBounds: { x: minX, y: minY, w: boundsWidth, h: boundsHeight },
      scale: nextScale,
      offset: { x: (MAP_WIDTH - mapContentW) / 2, y: (MAP_HEIGHT - mapContentH) / 2 },
    };
  }, [nodes]);

  // 世界坐标 → 小地图坐标
  const toMinimap = useCallback(
    (worldX: number, worldY: number) => ({
      x: (worldX - worldBounds.x) * scale + offset.x,
      y: (worldY - worldBounds.y) * scale + offset.y,
    }),
    [offset.x, offset.y, scale, worldBounds.x, worldBounds.y],
  );

  // 小地图坐标 → 世界坐标
  const toWorld = useCallback(
    (minimapX: number, minimapY: number) => ({
      x: (minimapX - offset.x) / scale + worldBounds.x,
      y: (minimapY - offset.y) / scale + worldBounds.y,
    }),
    [offset.x, offset.y, scale, worldBounds.x, worldBounds.y],
  );

  // 将当前视口（世界坐标范围）映射为小地图上的视口矩形
  const viewportRect = useMemo(() => {
    const vx = -viewport.x / viewport.scale;
    const vy = -viewport.y / viewport.scale;
    const vw = viewportSize.width / viewport.scale;
    const vh = viewportSize.height / viewport.scale;
    const p1 = toMinimap(vx, vy);
    const p2 = toMinimap(vx + vw, vy + vh);
    return {
      x: p1.x,
      y: p1.y,
      w: Math.max(p2.x - p1.x, 4),
      h: Math.max(p2.y - p1.y, 4),
    };
  }, [toMinimap, viewport.x, viewport.y, viewport.scale, viewportSize.width, viewportSize.height]);

  // 小地图指针位置反算世界坐标，并以该点作为视口中心导航
  const updateViewportFromEvent = (event: ReactPointerEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const world = toWorld(event.clientX - rect.left, event.clientY - rect.top);
    onViewportChange({
      x: viewportSize.width / 2 - world.x * viewport.scale,
      y: viewportSize.height / 2 - world.y * viewport.scale,
      scale: viewport.scale,
    });
  };

  return (
    <div
      className="absolute bottom-28 right-6 z-50 overflow-hidden rounded-lg border border-[#393633] bg-[#211f1d]/95 shadow-2xl backdrop-blur"
      style={{ width: MAP_WIDTH, height: MAP_HEIGHT }}
      // 阻止事件冒泡到画布，避免触发画布平移 / 框选
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div
        ref={containerRef}
        className="relative h-full w-full cursor-crosshair"
        onPointerDown={(event) => {
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          setIsDragging(true);
          updateViewportFromEvent(event);
        }}
        onPointerMove={(event) => {
          if (isDragging) updateViewportFromEvent(event);
        }}
        onPointerUp={() => setIsDragging(false)}
        onPointerLeave={() => setIsDragging(false)}
      >
        {nodes.map((node) => {
          const pos = toMinimap(node.position.x, node.position.y);
          const w = node.width ?? DEFAULT_NODE_WIDTH;
          const h = node.height ?? DEFAULT_NODE_HEIGHT;
          return (
            <div
              key={node.id}
              className="absolute rounded-[1px] opacity-80"
              style={{
                left: pos.x,
                top: pos.y,
                width: Math.max(w * scale, 2),
                height: Math.max(h * scale, 2),
                backgroundColor: nodeColor(node.type),
              }}
            />
          );
        })}
        {/* 视口矩形：蓝色描边 + 半透明填充，不参与指针事件 */}
        <div
          className="pointer-events-none absolute border"
          style={{
            left: viewportRect.x,
            top: viewportRect.y,
            width: viewportRect.w,
            height: viewportRect.h,
            borderColor: '#60a5fa',
            background: 'rgba(96,165,250,.15)',
          }}
        />
      </div>
    </div>
  );
}