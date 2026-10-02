import { describe, expect, it } from 'vitest';
import { buildReferenceEdges, collectAssets, summarizeAssets, type LibNode } from './assetLibrary';

const node = (id: string, config: Record<string, unknown>, result?: unknown, type = 'image'): LibNode => ({ id, type, data: { config, result } });
const hero = node('hero', { asset_role: 'character', asset_name: '林晚', scene_ids: ['s1'], profile: '设计师', locked: true, asset_id: 1 }, { url: '/a.png' });
const room = node('room', { asset_role: 'scene', asset_name: '宴会厅（夜）', scene_ids: ['s1'], prompt: '金色大厅' });
const umbrella = node('umbrella', { asset_role: 'prop', asset_name: '雨伞', scene_ids: ['s2'], prompt: '黑色长柄伞', asset_id: 9 });
const shot = (id: string, config: Record<string, unknown> = {}) => node(id, { node_role: 'storyboard', ...config });

describe('collectAssets', () => {
  it('角色、场景、道具按类别排序，设定字段各取所需', () => {
    const entries = collectAssets([umbrella, room, hero], []);
    expect(entries.map((e) => e.kind)).toEqual(['character', 'scene', 'prop']);
    expect(entries[0].setting).toBe('设计师');
    expect(entries[1].setting).toBe('金色大厅');
  });

  it('角色按名字或场景匹配，场景与道具只按场景重叠匹配', () => {
    const shots = [shot('a', { characters: ['林晚'] }), shot('b', { source_scene_ids: ['s1'] }), shot('c', { source_scene_ids: ['s2'] })];
    const byName = Object.fromEntries(collectAssets([hero, room, umbrella, ...shots], []).map((e) => [e.nodeId, e.appearances]));
    expect(byName.hero).toEqual(['a', 'b']);
    expect(byName.room).toEqual(['b']);
    expect(byName.umbrella).toEqual(['c']);
  });

  it('找出缺少引用的镜头', () => {
    const entries = collectAssets([room, shot('a', { source_scene_ids: ['s1'] }), shot('b', { source_scene_ids: ['s1'] })], [{ source: 'room', target: 'a', targetHandle: 'references' }]);
    expect(entries[0].missingRefs).toEqual(['b']);
  });

  it('过期节点、非资产图片和分镜不出现', () => {
    const entries = collectAssets([node('old', { asset_role: 'scene', asset_name: '旧', stale: true }), shot('s'), node('plain', {})], []);
    expect(entries).toEqual([]);
  });

  it('生成状态：有 asset_id 或结果图即视为已生成', () => {
    const byId = Object.fromEntries(collectAssets([hero, umbrella, room], []).map((entry) => [entry.nodeId, entry.hasImage]));
    expect(byId).toEqual({ hero: true, umbrella: true, room: false });
  });
});

describe('summarizeAssets', () => {
  it('统计各类数量、未生成和缺引用', () => {
    const entries = collectAssets([hero, room, umbrella, shot('a', { source_scene_ids: ['s1'] })], []);
    expect(summarizeAssets(entries)).toEqual({ total: 3, byKind: { character: 1, scene: 1, prop: 1 }, withoutImage: 1, missingRefs: 2 });
  });
});

describe('buildReferenceEdges', () => {
  it('只为尚未连线的镜头创建引用边', () => {
    const edges = buildReferenceEdges('hero', ['a', 'b'], [{ source: 'hero', target: 'a', targetHandle: 'references' }]);
    expect(edges.map((e) => e.target)).toEqual(['b']);
    expect(edges[0]).toMatchObject({ sourceHandle: 'image', targetHandle: 'references' });
  });
});
