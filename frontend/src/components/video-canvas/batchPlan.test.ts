import { describe, expect, it } from 'vitest';
import { collectProduction, generationAncestors, planBatchWaves, type BatchNode } from './batchPlan';

const node = (id: string, type: string, config: Record<string, unknown> = {}, result?: unknown): BatchNode => ({ id, type, data: { label: id, config, result } });
const edge = (source: string, target: string) => ({ source, target });

const hero = node('hero', 'image', { asset_role: 'character' });
const shotA = node('shotA', 'image', { node_role: 'storyboard', sequence: 1, source_scene_node: 's' });
const shotB = node('shotB', 'image', { node_role: 'storyboard', sequence: 2, source_scene_node: 's' });
const videoA = node('videoA', 'video', { source_scene_node: 's', sequence: 1, duration_seconds: 6 });
const scene = node('s', 'scene');
const edges = [edge('hero', 'shotA'), edge('hero', 'shotB'), edge('s', 'shotA'), edge('shotA', 'videoA')];
const all = [hero, shotA, shotB, videoA, scene];

describe('generationAncestors', () => {
  it('沿连线向上找到全部生成节点，穿过场景等非生成节点', () => {
    expect([...generationAncestors('videoA', all, edges)].sort()).toEqual(['hero', 'shotA']);
  });
});

describe('planBatchWaves', () => {
  it('互不依赖的节点在同一波次并行', () => {
    const plan = planBatchWaves(all, edges, ['shotA', 'shotB', 'hero']);
    expect(plan.waves).toEqual([['hero'], ['shotA', 'shotB']]);
    expect(plan.added).toEqual([]);
  });

  it('依赖的上游尚未生成时自动加入并排在前面', () => {
    const plan = planBatchWaves(all, edges, ['videoA']);
    expect(plan.waves).toEqual([['hero'], ['shotA'], ['videoA']]);
    expect(plan.added.sort()).toEqual(['hero', 'shotA']);
  });

  it('上游已生成则不重复加入，已生成的选中项被跳过', () => {
    const generatedHero = node('hero', 'image', { asset_role: 'character', asset_id: 1 });
    const plan = planBatchWaves([generatedHero, shotA, shotB, videoA, scene], edges, ['shotA', 'shotB', 'hero']);
    expect(plan.waves).toEqual([['shotA', 'shotB']]);
    expect(plan.skipped).toEqual(['hero']);
  });

  it('非生成节点被忽略，连线环不会死循环', () => {
    const cyclic = [node('x', 'image'), node('y', 'image')];
    const plan = planBatchWaves(cyclic, [edge('x', 'y'), edge('y', 'x')], ['x', 'y', 'scene']);
    expect(plan.waves).toEqual([]);
  });
});

describe('collectProduction', () => {
  it('分镜与视频按镜头序号排列，并标出生成状态', () => {
    const generated = node('shotB', 'image', { node_role: 'storyboard', sequence: 2 }, { url: '/b.png' });
    const entries = collectProduction([videoA, generated, shotA, hero, node('old', 'image', { node_role: 'storyboard', stale: true })]);
    expect(entries.map((e) => e.nodeId)).toEqual(['shotA', 'videoA', 'shotB']);
    expect(entries.find((e) => e.nodeId === 'shotB')).toMatchObject({ generated: true, mediaUrl: '/b.png', kind: 'storyboard' });
    expect(entries.find((e) => e.nodeId === 'videoA')).toMatchObject({ kind: 'video', duration: 6 });
  });
});

describe('planBatchWaves 重新生成', () => {
  it('已生成的选中项也会重新生成，锁定的除外，不自动带上游', () => {
    const generatedHero = node('hero', 'image', { asset_role: 'character', asset_id: 1 });
    const lockedShot = node('shotB', 'image', { node_role: 'storyboard', asset_id: 2, locked: true });
    const doneShot = node('shotA', 'image', { node_role: 'storyboard', asset_id: 3 });
    const plan = planBatchWaves([generatedHero, doneShot, lockedShot], [edge('hero', 'shotA')], ['hero', 'shotA', 'shotB'], { regenerate: true });
    expect(plan.waves).toEqual([['hero'], ['shotA']]);
    expect(plan.skipped).toEqual(['shotB']);
    expect(plan.added).toEqual([]);
  });
});
