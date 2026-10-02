import { describe, expect, it } from 'vitest';
import { computePipeline, continuePrompt, formatCostLine, formatRegenerateCost, type PipelineNode } from './canvasPipeline';

const node = (id: string, type: string, config: Record<string, unknown> = {}, result?: unknown): PipelineNode => ({ id, type, data: { config, result } });
const state = (summary: ReturnType<typeof computePipeline>, key: string) => summary.stages.find((s) => s.key === key)?.state;

describe('computePipeline', () => {
  it('空画布：第一步为下一步，其余待办', () => {
    const summary = computePipeline([], null, false);
    expect(state(summary, 'screenplay')).toBe('next');
    expect(state(summary, 'concat')).toBe('pending');
    expect(summary.next?.key).toBe('screenplay');
  });

  it('拆分后未批准：提示等待批准，导演为下一步', () => {
    const summary = computePipeline([node('s', 'screenplay', { content: '剧本' }), node('c', 'scene', { approved: false })], null, false);
    expect(state(summary, 'split')).toBe('done');
    expect(summary.awaitingSceneApproval).toBe(true);
    expect(summary.next?.key).toBe('director');
  });

  it('助手运行中：当前阶段为 active', () => {
    const summary = computePipeline([node('s', 'screenplay', { content: '剧本' })], null, true);
    expect(state(summary, 'split')).toBe('active');
  });

  it('编排完成后下一步是出图，需要用户提交，并统计待生成数量', () => {
    const nodes = [
      node('s', 'screenplay', { content: '剧本' }),
      node('c', 'scene', { approved: true, director_plan: { units: [] } }),
      node('a', 'image', { asset_role: 'character' }),
      node('b', 'image', { node_role: 'storyboard', source_scene_node: 'c' }),
      node('v', 'video', { source_scene_node: 'c' }),
    ];
    const summary = computePipeline(nodes, null, false);
    expect(summary.next?.key).toBe('images');
    expect(summary.next?.byAgent).toBe(false);
    expect(summary.pendingImages).toBe(2);
    expect(summary.pendingVideos).toBe(1);
    expect(summary.pendingAssetIds).toEqual(['a']);
    expect(summary.pendingShotIds).toEqual(['b']);
    expect(summary.pendingVideoIds).toEqual(['v']);
    expect(summary.shotsCompiled).toBe(true);
  });

  it('过期节点不参与判断', () => {
    const summary = computePipeline([node('s', 'screenplay', { content: '剧本', stale: true })], null, false);
    expect(state(summary, 'screenplay')).toBe('next');
  });

  it('生成失败时标出失败阶段与原因', () => {
    const nodes = [
      node('s', 'screenplay', { content: '剧本' }),
      node('c', 'scene', { approved: true, director_plan: {} }),
      node('a', 'image', { asset_role: 'scene' }, { url: 'x' }),
      node('b', 'image', { node_role: 'storyboard', source_scene_node: 'c' }),
      node('v', 'video', { source_scene_node: 'c' }),
    ];
    const summary = computePipeline(nodes, { status: 'failed', nodes: [{ status: 'failed', node_type: 'image', error_message: '内容审核未通过' }] }, false);
    expect(state(summary, 'images')).toBe('failed');
    expect(summary.failure).toBe('内容审核未通过');
  });
});

describe('continuePrompt', () => {
  it('为助手阶段提供明确指令', () => {
    expect(continuePrompt('director')).toContain('导演');
  });
});

describe('formatCostLine', () => {
  const base = { image_count: 3, video_count: 2, video_seconds: 15, total_points: 12.5, available_points: 30, sufficient: true };
  it('积分模式显示预估与余额', () => {
    const line = formatCostLine({ ...base, credential_mode: 'platform' });
    expect(line).toContain('预估 12.5 积分');
    expect(line).toContain('余额 30');
  });
  it('余额不足时明确提示', () => {
    expect(formatCostLine({ ...base, credential_mode: 'platform', available_points: 5, sufficient: false })).toContain('不足');
  });
  it('自带 Key 模式不显示积分', () => {
    const line = formatCostLine({ ...base, credential_mode: 'user_key', total_points: null, available_points: null, sufficient: null });
    expect(line).toContain('自有 API Key');
    expect(line).not.toContain('积分');
  });
});

describe('formatRegenerateCost', () => {
  it('积分模式提示花费与上游节点数', () => {
    expect(formatRegenerateCost({ credential_mode: 'platform', total_points: 9.5, image_count: 1, video_count: 1, video_seconds: 5 })).toBe('约 9.5 积分，含上游 1 个节点');
  });
  it('单个节点不提示上游，自带 Key 不显示积分', () => {
    expect(formatRegenerateCost({ credential_mode: 'platform', total_points: 2, image_count: 1, video_count: 0, video_seconds: 0 })).toBe('约 2 积分');
    expect(formatRegenerateCost({ credential_mode: 'user_key', total_points: null, image_count: 1, video_count: 0, video_seconds: 0 })).toBe('自有 API Key');
  });
});

describe('一键批量生成所需的待生成列表', () => {
  it('已生成的节点不再出现，镜头未编译前不允许一键生成', () => {
    const nodes = [
      node('s', 'screenplay', { content: '剧本' }),
      node('c', 'scene', { approved: true, director_plan: {} }),
      node('a1', 'image', { asset_role: 'character' }, { url: 'x' }),
      node('a2', 'image', { asset_role: 'prop' }),
    ];
    const summary = computePipeline(nodes, null, false);
    expect(summary.pendingAssetIds).toEqual(['a2']);
    expect(summary.shotsCompiled).toBe(false);
  });
});

describe('孤儿资产不计入进度', () => {
  it('旧剧本留下、所属场景已不存在的资产：拆分未完成时“资产”不能显示为已完成', () => {
    const nodes = [
      node('sp', 'screenplay', { content: '新剧本' }),
      node('hero', 'image', { asset_role: 'character', asset_scene_node: 'scene-old' }),
      node('prop', 'image', { asset_role: 'prop', source_scene_node: 'scene-old' }),
    ];
    const summary = computePipeline(nodes, null, true);
    expect(state(summary, 'split')).toBe('active');
    expect(state(summary, 'assets')).toBe('pending');
    expect(summary.pendingImages).toBe(0);
    expect(summary.pendingAssetIds).toEqual([]);
  });

  it('属于当前场景的资产、以及用户手动加的无归属资产照常计入', () => {
    const nodes = [
      node('sp', 'screenplay', { content: '剧本' }),
      node('scene-1', 'scene', { approved: true, director_plan: {} }),
      node('hero', 'image', { asset_role: 'character', asset_scene_node: 'scene-1' }),
      node('manual', 'image', { asset_role: 'prop' }),
    ];
    const summary = computePipeline(nodes, null, false);
    expect(state(summary, 'assets')).toBe('done');
    expect(summary.pendingAssetIds.sort()).toEqual(['hero', 'manual']);
  });
});

