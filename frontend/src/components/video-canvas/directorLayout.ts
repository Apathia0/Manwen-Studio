/**
 * 导演视频单元的稳定布局：按 sequence 排成横向时间线，自动避让已有节点。
 * 坐标只影响视觉呈现；剧情顺序始终由 unit.sequence / edge metadata 表达。
 */

export interface DirectorLayoutUnit {
  sequence: number;
  unit_id: string;
}

export interface DirectorLayoutRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DirectorLayoutOptions {
  nodeWidth?: number;
  nodeHeight?: number;
  gapX?: number;
  gapY?: number;
  maxPerRow?: number;
}

/** 稳定节点 ID：同一场景同一单元重复应用时身份不变，不产生重复节点组 */
export function unitNodeId(sceneNodeId: string, unitId: string): string {
  const safeScene = sceneNodeId.replace(/[^A-Za-z0-9_-]/g, '') || 'scene';
  const safeUnit = unitId.replace(/[^A-Za-z0-9_-]/g, '') || 'unit';
  const suffix = `${safeScene}-${safeUnit}`;
  if (suffix.length <= 56) return `dir-${suffix}`;
  // Preserve deterministic identity without silently colliding two long IDs.
  let hash = 2166136261;
  for (const char of suffix) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  const digest = (hash >>> 0).toString(36).padStart(7, '0');
  return `dir-${suffix.slice(0, 48)}-${digest}`.slice(0, 64);
}

function intersects(a: DirectorLayoutRect, b: DirectorLayoutRect): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

/**
 * 按导演 sequence 排序并分配时间线坐标：
 * - 从锚点右侧开始横向排列，超出 maxPerRow 换行；
 * - 每个候选位置先检查与 existingNodes 碰撞，被占用则沿当前行向后扫描；
 * - 输出按输入顺序（应已按 sequence），坐标与 unit 一一对应。
 */
export function layoutDirectorUnits(
  units: DirectorLayoutUnit[],
  anchor: { x: number; y: number },
  existingNodes: DirectorLayoutRect[],
  options: DirectorLayoutOptions = {},
): Map<string, { x: number; y: number }> {
  const width = options.nodeWidth ?? 340;
  const height = options.nodeHeight ?? 220;
  const gapX = options.gapX ?? 40;
  const gapY = options.gapY ?? 60;
  const maxPerRow = Math.max(1, options.maxPerRow ?? 4);

  const positions = new Map<string, { x: number; y: number }>();
  const occupied = [...existingNodes];
  const sorted = [...units].sort((left, right) => left.sequence - right.sequence);

  let row = 0;
  let column = 0;
  for (const unit of sorted) {
    const rect: DirectorLayoutRect = { x: 0, y: 0, width, height };
    let placed = false;
    // 从当前行列开始向后扫描，直到找到不碰撞的位置
    while (!placed) {
      rect.x = anchor.x + column * (width + gapX);
      rect.y = anchor.y + row * (height + gapY);
      if (!occupied.some((other) => intersects(rect, other))) {
        placed = true;
      } else {
        column += 1;
        if (column >= maxPerRow * 4) {
          column = 0;
          row += 1;
        }
      }
    }
    occupied.push({ ...rect });
    positions.set(unit.unit_id, { x: rect.x, y: rect.y });
    column += 1;
    if (column >= maxPerRow) {
      column = 0;
      row += 1;
    }
  }
  return positions;
}
