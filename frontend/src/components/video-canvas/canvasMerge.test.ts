import { describe, expect, it } from 'vitest';
import type { VideoCanvasGraph } from '../../api';
import { mergeCanvasGraphs } from './canvasMerge';

const node = (id: string, config: Record<string, unknown> = {}, position = { x: 0, y: 0 }) =>
  ({ id, type: 'image', position, data: { label: id, config } }) as unknown as VideoCanvasGraph['nodes'][number];
const edge = (id: string, source: string, target: string) => ({ id, source, target, sourceHandle: 'image', targetHandle: 'references' }) as unknown as VideoCanvasGraph['edges'][number];
const graph = (nodes: VideoCanvasGraph['nodes'], edges: VideoCanvasGraph['edges'] = [], metadata: Record<string, unknown> = {}) =>
  ({ schema_version: 1, nodes, edges, groups: [], metadata }) as unknown as VideoCanvasGraph;

describe('mergeCanvasGraphs', () => {
  it('后台更新了资产（提示词、恢复存活），本地只是旧快照：保留后台的新内容，不被本地旧内容覆盖', () => {
    const base = graph([node('hero', { prompt: '旧提示词', stale: true })]);
    const local = base; // 本地没动过这个节点
    const server = graph([node('hero', { prompt: '新提示词', stale: false })]);
    const { graph: merged, conflicts } = mergeCanvasGraphs(base, local, server);
    expect(merged.nodes[0].data.config).toMatchObject({ prompt: '新提示词', stale: false });
    expect(conflicts).toEqual([]);
  });

  it('本地改了提示词、后台改了别的字段：两边的修改都保留', () => {
    const base = graph([node('hero', { prompt: 'a', asset_id: null })]);
    const local = graph([node('hero', { prompt: '我改的', asset_id: null })]);
    const server = graph([node('hero', { prompt: 'a', asset_id: 9 })]);
    const { graph: merged, conflicts } = mergeCanvasGraphs(base, local, server);
    expect(merged.nodes[0].data.config).toMatchObject({ prompt: '我改的', asset_id: 9 });
    expect(conflicts).toEqual([]);
  });

  it('两边改了同一个字段：以后台为准并报告冲突', () => {
    const base = graph([node('hero', { prompt: 'a' })]);
    const { graph: merged, conflicts } = mergeCanvasGraphs(base, graph([node('hero', { prompt: '本地' })]), graph([node('hero', { prompt: '后台' })]));
    expect(merged.nodes[0].data.config?.prompt).toBe('后台');
    expect(conflicts.join()).toContain('prompt');
  });

  it('后台新增的节点和连线保留，本地新增的也保留；本地挪动的位置保留', () => {
    const base = graph([node('a')]);
    const local = graph([node('a', {}, { x: 50, y: 60 }), node('mine')]);
    const server = graph([node('a'), node('theirs')], [edge('e1', 'a', 'theirs')]);
    const { graph: merged } = mergeCanvasGraphs(base, local, server);
    expect(merged.nodes.map((n) => n.id).sort()).toEqual(['a', 'mine', 'theirs']);
    expect(merged.nodes.find((n) => n.id === 'a')?.position).toEqual({ x: 50, y: 60 });
    expect(merged.edges.map((e) => e.id)).toEqual(['e1']);
  });

  it('本地删除的节点：后台没动就删掉，后台改过就保留后台的；指向已删节点的连线一并去掉', () => {
    const base = graph([node('a'), node('b', { v: 1 }), node('c', { v: 1 })], [edge('e1', 'a', 'b'), edge('e2', 'a', 'c')]);
    const local = graph([node('a')], []);
    const server = graph([node('a'), node('b', { v: 1 }), node('c', { v: 2 })], [edge('e1', 'a', 'b'), edge('e2', 'a', 'c')]);
    const { graph: merged, conflicts } = mergeCanvasGraphs(base, local, server);
    expect(merged.nodes.map((n) => n.id).sort()).toEqual(['a', 'c']);
    expect(merged.edges.map((e) => e.id)).toEqual(['e2']);
    expect(conflicts.join()).toContain('c');
  });

  it('开场卡片设置的画幅 / 固定15秒 / 画风始终以本地为准，后台写的其他元数据保留', () => {
    const base = graph([], [], {});
    const local = graph([], [], { production_settings: { shot_duration_mode: 'fixed15', aspect_ratio: '16:9' }, canvas_style: { enabled: true } });
    const server = graph([], [], { production_settings: {}, agent_stage_actions: { x: 1 } });
    const { graph: merged } = mergeCanvasGraphs(base, local, server);
    expect(merged.metadata).toMatchObject({
      production_settings: { shot_duration_mode: 'fixed15', aspect_ratio: '16:9' },
      canvas_style: { enabled: true },
      agent_stage_actions: { x: 1 },
    });
  });
});
