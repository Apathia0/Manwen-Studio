import { describe, expect, it } from 'vitest';
import { ASSET_CELL_H, ASSET_CELL_W, ASSET_SCENE_GAP, nextAssetSlot, planAssetPositions } from './assetLayout';

const scene = { position: { x: 1000, y: 200 }, width: 1280 };
const startX = 1000 + 1280 + ASSET_SCENE_GAP;

describe('planAssetPositions', () => {
  it('角色一列、道具一列、场景一列，在场景审核右侧，与场景顶部对齐', () => {
    const items = [
      ...Array.from({ length: 5 }, (_, i) => ({ id: `c${i}`, kind: 'character' as const })),
      { id: 's0', kind: 'scene' as const },
      { id: 'p0', kind: 'prop' as const },
    ];
    const pos = planAssetPositions(scene, items);
    expect(pos.get('c0')).toEqual({ x: startX, y: 200 });
    expect(pos.get('c4')).toEqual({ x: startX, y: 200 + 4 * ASSET_CELL_H });
    expect(pos.get('p0')).toEqual({ x: startX + ASSET_CELL_W, y: 200 });
    expect(pos.get('s0')).toEqual({ x: startX + 2 * ASSET_CELL_W, y: 200 });
  });

  it('没有的类别不占栏位', () => {
    expect(planAssetPositions(scene, [{ id: 's0', kind: 'scene' }]).get('s0')).toEqual({ x: startX, y: 200 });
  });

  it('所有节点位置互不重叠', () => {
    const items = Array.from({ length: 30 }, (_, i) => ({ id: `n${i}`, kind: (['character', 'scene', 'prop'] as const)[i % 3] }));
    const pos = [...planAssetPositions(scene, items).values()];
    expect(new Set(pos.map((p) => `${p.x},${p.y}`)).size).toBe(pos.length);
  });
});

describe('nextAssetSlot', () => {
  it('接在同类最后一个下面', () => {
    const existing = Array.from({ length: 3 }, (_, i) => ({ kind: 'prop' as const, position: { x: 500, y: 900 + i * ASSET_CELL_H } }));
    expect(nextAssetSlot(scene, 'prop', existing)).toEqual({ x: 500, y: 900 + 3 * ASSET_CELL_H });
  });

  it('该类还没有时放到已有资产列的右侧，完全没有资产时放到场景审核右侧', () => {
    expect(nextAssetSlot(scene, 'scene', [{ kind: 'character', position: { x: 300, y: 900 } }])).toEqual({ x: 300 + ASSET_CELL_W, y: 900 });
    expect(nextAssetSlot(scene, 'prop', [])).toEqual({ x: startX, y: 200 });
  });
});
