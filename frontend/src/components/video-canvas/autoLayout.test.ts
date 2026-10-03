import { describe, expect, it } from 'vitest';
import { computeAutoLayout, type LayoutNode } from './autoLayout';

const node = (id: string, type: string, extra: Partial<LayoutNode> = {}): LayoutNode => ({ id, type, width: 420, height: 236, x: 0, y: 0, ...extra });

describe('computeAutoLayout', () => {
  const nodes = [
    node('sp', 'screenplay'),
    node('scene', 'scene', { width: 1280, height: 800 }),
    node('hero', 'image', { assetRole: 'character' }),
    node('hero2', 'image', { assetRole: 'character', y: 400 }),
    node('stone', 'image', { assetRole: 'prop' }),
    node('square', 'image', { assetRole: 'scene' }),
    node('sb1', 'image'),
    node('v1', 'video'),
  ];
  const edges = [
    { source: 'sp', target: 'scene' },
    { source: 'scene', target: 'sb1' },
    { source: 'hero', target: 'sb1' },
    { source: 'stone', target: 'sb1' },
    { source: 'square', target: 'sb1' },
    { source: 'sb1', target: 'v1' },
  ];

  it('角色一列、道具一列、场景一列，且排在场景审核之后、分镜之前', () => {
    const pos = computeAutoLayout(nodes, edges);
    const x = (id: string) => pos.get(id)!.x;
    expect(x('hero')).toBe(x('hero2'));
    expect(new Set([x('hero'), x('stone'), x('square')]).size).toBe(3);
    expect(x('hero')).toBeLessThan(x('stone'));
    expect(x('stone')).toBeLessThan(x('square'));
    expect(x('scene')).toBeLessThan(x('hero'));
    expect(x('square')).toBeLessThan(x('sb1'));
    expect(x('sb1')).toBeLessThan(x('v1'));
  });

  it('同一栏里的资产纵向排开且互不重叠，剧本不再和资产叠在一列', () => {
    const pos = computeAutoLayout(nodes, edges);
    expect(pos.get('hero2')!.y).toBeGreaterThan(pos.get('hero')!.y + 236);
    expect(pos.get('sp')!.x).not.toBe(pos.get('hero')!.x);
  });

  it('没有某类资产时不占栏位；没有场景节点也能排', () => {
    const pos = computeAutoLayout([node('sp', 'screenplay'), node('hero', 'image', { assetRole: 'character' }), node('sb1', 'image')], [{ source: 'sp', target: 'sb1' }]);
    expect(pos.get('hero')!.x).toBeGreaterThan(pos.get('sp')!.x);
    expect(pos.size).toBe(3);
  });

  it('只有资产节点时也能排', () => {
    const pos = computeAutoLayout([node('a', 'image', { assetRole: 'prop' }), node('b', 'image', { assetRole: 'scene' })], []);
    expect(pos.get('a')!.x).toBeLessThan(pos.get('b')!.x);
  });
});
