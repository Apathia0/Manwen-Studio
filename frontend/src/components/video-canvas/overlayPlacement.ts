export interface OverlayBounds {
  width: number;
  height: number;
}

export interface OverlaySize {
  width: number;
  height: number;
}

export interface OverlayPoint {
  x: number;
  y: number;
}

export interface OverlayInsets {
  top?: number;
  right?: number;
  bottom?: number;
  left?: number;
}

const DEFAULT_INSETS: Required<OverlayInsets> = { top: 12, right: 12, bottom: 12, left: 12 };

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

/** Keep an overlay fully inside its containing canvas. */
export function clampOverlayPosition(
  preferred: OverlayPoint,
  size: OverlaySize,
  bounds: OverlayBounds,
  insets: OverlayInsets = {},
): OverlayPoint {
  const safe = { ...DEFAULT_INSETS, ...insets };
  return {
    x: clamp(preferred.x, safe.left, bounds.width - size.width - safe.right),
    y: clamp(preferred.y, safe.top, bounds.height - size.height - safe.bottom),
  };
}

export interface InspectorPlacementInput {
  anchor: { x: number; y: number; width: number; height: number };
  size: OverlaySize;
  bounds: OverlayBounds;
  gap?: number;
  insets?: OverlayInsets;
}

/** Place the inspector anchored below the node, left-aligned with it. */
export function placeInspector({ anchor, size, bounds, gap = 16, insets = {} }: InspectorPlacementInput): OverlayPoint {
  const safe = { ...DEFAULT_INSETS, ...insets };
  return {
    x: clamp(anchor.x, safe.left, bounds.width - size.width - safe.right),
    y: Math.max(anchor.y + anchor.height + gap, safe.top),
  };
}

export interface FocusViewportInput {
  node: { x: number; y: number; width: number; height: number };
  bounds: OverlayBounds;
  /** 顶部与底部被浮层（顶栏、输入框、工具栏）占用的高度 */
  reserved: { top: number; bottom: number };
  minScale?: number;
  maxScale?: number;
}

/** 计算「聚焦节点」视口：节点在未被输入框遮挡的区域内居中，缩放以完整可见为准。 */
export function computeFocusViewport({ node, bounds, reserved, minScale = 0.1, maxScale = 1 }: FocusViewportInput): { x: number; y: number; k: number } {
  const areaHeight = Math.max(120, bounds.height - reserved.top - reserved.bottom);
  const fit = Math.min(maxScale, (bounds.width * 0.6) / Math.max(1, node.width), (areaHeight * 0.9) / Math.max(1, node.height));
  const k = Math.min(maxScale, Math.max(minScale, fit));
  return {
    k,
    x: bounds.width / 2 - (node.x + node.width / 2) * k,
    y: reserved.top + areaHeight / 2 - (node.y + node.height / 2) * k,
  };
}
