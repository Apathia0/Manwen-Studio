/** 资产节点分栏布局：角色 / 场景 / 道具各占一栏，放在场景节点下方（与后端 canvas_stage_gateway 的常量一致）。 */

import type { AssetKind } from './assetLibrary';

export const ASSET_CELL_W = 340;
export const ASSET_CELL_H = 260;
export const ASSET_ROWS_PER_COLUMN = 4;
export const ASSET_BLOCK_GAP = 120;
const KIND_ORDER: AssetKind[] = ['character', 'scene', 'prop'];

export interface Point { x: number; y: number }

/** 为一批新资产计算位置：每类一栏，每栏最多 4 行，超出向右换列，栏之间留出间距。 */
export function planAssetPositions(sceneNode: { position: Point; height?: number }, items: Array<{ id: string; kind: AssetKind }>): Map<string, Point> {
  const result = new Map<string, Point>();
  const top = sceneNode.position.y + (sceneNode.height || 640) + ASSET_BLOCK_GAP;
  let cursorX = sceneNode.position.x;
  for (const kind of KIND_ORDER) {
    const group = items.filter((item) => item.kind === kind);
    if (!group.length) continue;
    group.forEach((item, index) => {
      result.set(item.id, { x: cursorX + Math.floor(index / ASSET_ROWS_PER_COLUMN) * ASSET_CELL_W, y: top + (index % ASSET_ROWS_PER_COLUMN) * ASSET_CELL_H });
    });
    cursorX += Math.ceil(group.length / ASSET_ROWS_PER_COLUMN) * ASSET_CELL_W + ASSET_BLOCK_GAP;
  }
  return result;
}

/** 给已有的一栏追加一个资产时的落点：接在该类最后一个之后；该类还没有时放到已有资产的右侧。 */
export function nextAssetSlot(sceneNode: { position: Point; height?: number }, kind: AssetKind, existing: Array<{ kind: AssetKind; position: Point }>): Point {
  const same = existing.filter((item) => item.kind === kind);
  if (same.length) {
    const originX = Math.min(...same.map((item) => item.position.x));
    const top = Math.min(...same.map((item) => item.position.y));
    return { x: originX + Math.floor(same.length / ASSET_ROWS_PER_COLUMN) * ASSET_CELL_W, y: top + (same.length % ASSET_ROWS_PER_COLUMN) * ASSET_CELL_H };
  }
  const top = existing.length ? Math.min(...existing.map((item) => item.position.y)) : sceneNode.position.y + (sceneNode.height || 640) + ASSET_BLOCK_GAP;
  const x = existing.length ? Math.max(...existing.map((item) => item.position.x)) + ASSET_CELL_W + ASSET_BLOCK_GAP : sceneNode.position.x;
  return { x, y: top };
}
