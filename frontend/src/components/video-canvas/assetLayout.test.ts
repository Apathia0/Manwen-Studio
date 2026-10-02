import { describe, expect, it } from 'vitest';
import { ASSET_BLOCK_GAP, ASSET_CELL_H, ASSET_CELL_W, nextAssetSlot, planAssetPositions } from './assetLayout';

const scene = { position: { x: 1000, y: 200 }, height: 600 };
const top = 200 + 600 + ASSET_BLOCK_GAP;

describe('planAssetPositions', () => {
  it('每类一栏、每栏 4 行，超出换列，栏间留间距', () => {
    const items = [
      ...Array.from({ length: 5 }, (_, i) => ({ id: `c${i}`, kind: 'character' as const })),
      { id: 's0', kind: 'scene' as const },
      { id: 'p0', kind: 'prop' as const },
    ];
    const pos = planAssetPositions(scene, items);
    expect(pos.get('c0')).toEqual({ x: 1000, y: top });
    expect(pos.get('c3')).toEqual({ x: 1000, y: top + 3 * ASSET_CELL_H });
    expect(pos.get('c4')).toEqual({ x: 1000 + ASSET_CELL_W, y: top });
    expect(pos.get('s0')).toEqual({ x: 1000 + 2 * ASSET_CELL_W + ASSET_BLOCK_GAP, y: top });
    expect(pos.get('p0')!.x).toBe(pos.get('s0')!.x + ASSET_CELL_W + ASSET_BLOCK_GAP);
  });

  it('没有的类别不占栏位', () => {
    const pos = planAssetPositions(scene, [{ id: 'p0', kind: 'prop' }]);
    expect(pos.get('p0')).toEqual({ x: 1000, y: top });
  });

  it('所有节点位置互不重叠', () => {
    const items = Array.from({ length: 30 }, (_, i) => ({ id: `n${i}`, kind: (['character', 'scene', 'prop'] as const)[i % 3] }));
    const pos = [...planAssetPositions(scene, items).values()];
    const keys = new Set(pos.map((p) => `${p.x},${p.y}`));
    expect(keys.size).toBe(pos.length);
  });
});

describe('nextAssetSlot', () => {
  it('接在同类最后一个之后，满 4 个换列', () => {
    const existing = Array.from({ length: 4 }, (_, i) => ({ kind: 'prop' as const, position: { x: 500, y: 900 + i * ASSET_CELL_H } }));
    expect(nextAssetSlot(scene, 'prop', existing)).toEqual({ x: 500 + ASSET_CELL_W, y: 900 });
    expect(nextAssetSlot(scene, 'prop', existing.slice(0, 2))).toEqual({ x: 500, y: 900 + 2 * ASSET_CELL_H });
  });

  it('该类还没有时放到已有资产右侧，完全没有资产时放到场景下方', () => {
    expect(nextAssetSlot(scene, 'scene', [{ kind: 'character', position: { x: 300, y: 900 } }])).toEqual({ x: 300 + ASSET_CELL_W + ASSET_BLOCK_GAP, y: 900 });
    expect(nextAssetSlot(scene, 'prop', [])).toEqual({ x: 1000, y: top });
  });
});
