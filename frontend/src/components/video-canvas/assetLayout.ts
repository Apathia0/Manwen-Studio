/** 资产节点分栏布局：角色一列、道具一列、场景一列，放在场景审核节点右侧（与后端 canvas_stage_gateway 的常量一致）。 */

import type { AssetKind } from './assetLibrary';

export const ASSET_CELL_W = 460;
export const ASSET_CELL_H = 290;
export const ASSET_SCENE_GAP = 160;
export const SCENE_DEFAULT_WIDTH = 1280;
/** 栏的先后顺序：角色、道具、场景 */
const KIND_ORDER: AssetKind[] = ['character', 'prop', 'scene'];

export interface Point { x: number; y: number }
export interface SceneBox { position: Point; width?: number }

function startX(scene: SceneBox): number {
  return scene.position.x + (scene.width || SCENE_DEFAULT_WIDTH) + ASSET_SCENE_GAP;
}

/** 为一批新资产计算位置：每类一列自上而下，列与列依次向右排，与场景审核节点顶部对齐。 */
export function planAssetPositions(scene: SceneBox, items: Array<{ id: string; kind: AssetKind }>): Map<string, Point> {
  const result = new Map<string, Point>();
  let x = startX(scene);
  for (const kind of KIND_ORDER) {
    const group = items.filter((item) => item.kind === kind);
    if (!group.length) continue;
    group.forEach((item, index) => result.set(item.id, { x, y: scene.position.y + index * ASSET_CELL_H }));
    x += ASSET_CELL_W;
  }
  return result;
}

/** 给已有的一列追加一个资产时的落点：接在该类最后一个下面；该类还没有时放到已有资产列的右侧；完全没有资产时放到场景审核节点右侧。 */
export function nextAssetSlot(scene: SceneBox, kind: AssetKind, existing: Array<{ kind: AssetKind; position: Point }>): Point {
  const same = existing.filter((item) => item.kind === kind);
  if (same.length) {
    return { x: Math.min(...same.map((item) => item.position.x)), y: Math.max(...same.map((item) => item.position.y)) + ASSET_CELL_H };
  }
  if (existing.length) {
    return { x: Math.max(...existing.map((item) => item.position.x)) + ASSET_CELL_W, y: Math.min(...existing.map((item) => item.position.y)) };
  }
  return { x: startX(scene), y: scene.position.y };
}
