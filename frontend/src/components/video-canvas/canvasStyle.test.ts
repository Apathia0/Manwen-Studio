import { describe, expect, it } from 'vitest';
import type { VideoCanvasGraph, VideoStylePreset } from '../../api';
import type { BatchNode } from './batchPlan';
import { anyFollowsCanvasStyle, hasOwnStyle, outdatedNodeIds, presetToCanvasStyle, readCanvasStyle, referenceToCanvasStyle, sameStyle, styleActive, styleDisplay, effectiveStyleKey, inconsistentNodeIds, styleKeyOfConfig } from './canvasStyle';

const preset: VideoStylePreset = { id: 3, name: '国风水墨', category: 'artistic', image_url: '/ink.png', prompt_template: '水墨晕染', image_style_params: { a: 1 }, video_style_params: null, sort_order: 1 };
const node = (id: string, type: string, config: Record<string, unknown> = {}, result?: unknown): BatchNode => ({ id, type, data: { config, result } });
const graph = (style: unknown): VideoCanvasGraph => ({ schema_version: 1, nodes: [], edges: [], metadata: style ? { canvas_style: style } : {} });

describe('画布风格的读写', () => {
  it('预设转成与后端一致的结构并能读回', () => {
    const style = presetToCanvasStyle(preset);
    expect(style).toMatchObject({ style_preset_id: 3, style_reference_asset_id: null });
    expect(style.style_snapshot).toMatchObject({ name: '国风水墨', prompt_template: '水墨晕染', image_url: '/ink.png', video_style_params: {} });
    expect(readCanvasStyle(graph(style))).toEqual(style);
  });

  it('自定义参考图风格与无效数据', () => {
    expect(readCanvasStyle(graph(referenceToCanvasStyle(9, '/ref.png')))).toMatchObject({ style_reference_asset_id: 9, style_reference_url: '/ref.png' });
    expect(readCanvasStyle(graph(null))).toBeNull();
    expect(readCanvasStyle(graph({ style_snapshot: {} }))).toBeNull();
    expect(readCanvasStyle(undefined)).toBeNull();
  });

  it('展示名称与缩略图', () => {
    expect(styleDisplay(null)).toEqual({ name: '未选择画风', imageUrl: null, enabled: false });
    expect(styleDisplay(presetToCanvasStyle(preset))).toEqual({ name: '国风水墨', imageUrl: '/ink.png', enabled: true });
    expect(styleDisplay(referenceToCanvasStyle(9, '/ref.png'))).toEqual({ name: '自定义参考图', imageUrl: '/ref.png', enabled: true });
  });

  it('相同风格判定', () => {
    expect(sameStyle(presetToCanvasStyle(preset), presetToCanvasStyle(preset))).toBe(true);
    expect(sameStyle(presetToCanvasStyle(preset), null)).toBe(false);
  });
});

describe('哪些节点跟随画布风格', () => {
  it('自带预设或参考图的节点不跟随', () => {
    expect(hasOwnStyle({ style_snapshot: { name: 'x' } })).toBe(true);
    expect(hasOwnStyle({ style_reference_asset_id: 4 })).toBe(true);
    expect(hasOwnStyle({ prompt: 'p' })).toBe(false);
    expect(hasOwnStyle({ style_snapshot: null })).toBe(false);
  });

  it('更换画风后需要重生成的：已生成、未锁定、跟随画布的图片/视频', () => {
    const nodes = [
      node('done', 'image', {}, { url: '/a.png' }),
      node('locked', 'image', { locked: true, asset_id: 1 }),
      node('own', 'image', { style_snapshot: { name: 'x' }, asset_id: 2 }),
      node('todo', 'image', {}),
      node('stale', 'image', { stale: true, asset_id: 3 }),
      node('clip', 'video', { asset_id: 5 }),
      node('text', 'text', {}),
    ];
    expect(outdatedNodeIds(nodes).sort()).toEqual(['clip', 'done']);
  });

  it('批量目标里有跟随画布风格的节点时才需要提示选风格', () => {
    const nodes = [node('a', 'image', {}), node('b', 'image', { style_reference_asset_id: 1 })];
    expect(anyFollowsCanvasStyle(nodes, ['a'])).toBe(true);
    expect(anyFollowsCanvasStyle(nodes, ['b'])).toBe(false);
  });
});

describe('全局画风开关', () => {
  it('默认开启，显式关闭后保留风格但不再生效', () => {
    const style = presetToCanvasStyle(preset);
    expect(readCanvasStyle(graph(style))?.enabled).toBe(true);
    const off = readCanvasStyle(graph({ ...style, enabled: false }));
    expect(off?.enabled).toBe(false);
    expect(off?.style_snapshot?.name).toBe('国风水墨');
    expect(styleActive(off)).toBe(false);
    expect(styleActive(style)).toBe(true);
    expect(styleActive(null)).toBe(false);
    expect(sameStyle(style, { ...style, enabled: false })).toBe(false);
  });
});

describe('一键统一画风：找出不一致的节点', () => {
  const style = presetToCanvasStyle(preset);
  const key = styleKeyOfConfig(style as unknown as Record<string, unknown>);
  const done = (id: string, recorded: string | undefined, extra: Record<string, unknown> = {}, config: Record<string, unknown> = {}, reused = false): BatchNode => ({
    id, type: 'image', data: { config, result: { url: '/x.png', reused }, ...(recorded === undefined ? {} : { result_style_key: recorded }), ...extra },
  });

  it('生成时的画风与现在不同的才算不一致', () => {
    const nodes = [done('same', key), done('old', ''), done('other', 'preset:赛博朋克||')];
    expect(inconsistentNodeIds(nodes, style).sort()).toEqual(['old', 'other']);
  });

  it('锁定、上传/固定的素材、没有记录的、过期的、自带风格的不算', () => {
    const nodes = [
      done('locked', '', {}, { locked: true }),
      done('pinned', '', {}, {}, true),
      done('unknown', undefined),
      done('stale', '', {}, { stale: true }),
      done('own', 'preset:赛博朋克||', {}, { style_snapshot: { name: '赛博朋克', prompt_template: '', image_url: null } }),
    ];
    expect(inconsistentNodeIds(nodes, style)).toEqual([]);
  });

  it('关闭全局画风后，带画风生成的结果变为不一致；没选画风时无风格的结果一致', () => {
    expect(inconsistentNodeIds([done('a', key)], { ...style, enabled: false })).toEqual(['a']);
    expect(inconsistentNodeIds([done('b', '')], null)).toEqual([]);
    expect(effectiveStyleKey({}, { ...style, enabled: false })).toBe('');
    expect(effectiveStyleKey({ style_reference_asset_id: 4 }, style)).toBe('ref:4');
  });
});
