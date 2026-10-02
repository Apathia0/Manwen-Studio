/** 画布级风格：整张画布统一的画风（风格预设或自定义参考图），与后端 services/canvas_style.py 的结构一致。 */

import type { VideoCanvasGraph, VideoStylePreset } from '../../api';
import { isGenerated, isGenerationNode, type BatchNode } from './batchPlan';

export interface StyleSnapshot {
  name: string;
  prompt_template: string;
  image_style_params: Record<string, unknown>;
  video_style_params: Record<string, unknown>;
  image_url: string | null;
}

export interface CanvasStyle {
  /** 全局画风开关：关闭后未单独设置风格的节点不使用画布风格，但风格本身保留，随时可再打开 */
  enabled: boolean;
  style_preset_id: number | null;
  style_snapshot: StyleSnapshot | null;
  style_reference_asset_id: number | null;
  style_reference_url: string | null;
}

export function presetToCanvasStyle(preset: VideoStylePreset): CanvasStyle {
  return {
    enabled: true,
    style_preset_id: preset.id,
    style_snapshot: {
      name: preset.name,
      prompt_template: preset.prompt_template || '',
      image_style_params: preset.image_style_params || {},
      video_style_params: preset.video_style_params || {},
      image_url: preset.image_url || null,
    },
    style_reference_asset_id: null,
    style_reference_url: null,
  };
}

export function referenceToCanvasStyle(assetId: number, url: string): CanvasStyle {
  return { enabled: true, style_preset_id: null, style_snapshot: null, style_reference_asset_id: assetId, style_reference_url: url };
}

/** 从图的 metadata 读取画布风格；没有有效风格返回 null。 */
export function readCanvasStyle(graph: VideoCanvasGraph | null | undefined): CanvasStyle | null {
  const raw = graph?.metadata?.canvas_style as Partial<CanvasStyle> | undefined;
  if (!raw || typeof raw !== 'object') return null;
  const hasSnapshot = Boolean(raw.style_snapshot && typeof raw.style_snapshot === 'object' && Object.keys(raw.style_snapshot).length);
  const hasReference = typeof raw.style_reference_asset_id === 'number';
  if (!hasSnapshot && !hasReference) return null;
  return {
    enabled: raw.enabled !== false,
    style_preset_id: typeof raw.style_preset_id === 'number' ? raw.style_preset_id : null,
    style_snapshot: hasSnapshot ? (raw.style_snapshot as StyleSnapshot) : null,
    style_reference_asset_id: hasReference ? (raw.style_reference_asset_id as number) : null,
    style_reference_url: typeof raw.style_reference_url === 'string' && raw.style_reference_url ? raw.style_reference_url : null,
  };
}

/** 界面上展示用的名称与缩略图。 */
export function styleDisplay(style: CanvasStyle | null): { name: string; imageUrl: string | null; enabled: boolean } {
  if (!style) return { name: '未选择画风', imageUrl: null, enabled: false };
  if (style.style_snapshot) return { name: style.style_snapshot.name || '自定义风格', imageUrl: style.style_snapshot.image_url, enabled: style.enabled };
  return { name: '自定义参考图', imageUrl: style.style_reference_url, enabled: style.enabled };
}

/** 画风当前是否真的会被使用（选了风格且开关打开）。 */
export function styleActive(style: CanvasStyle | null): boolean {
  return Boolean(style && style.enabled);
}

export function sameStyle(a: CanvasStyle | null, b: CanvasStyle | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** 节点是否自己设置了风格（设置过就不跟随画布风格）。 */
export function hasOwnStyle(config: Record<string, unknown> | undefined): boolean {
  const snapshot = config?.style_snapshot;
  return Boolean(snapshot && typeof snapshot === 'object' && Object.keys(snapshot as object).length) || typeof config?.style_reference_asset_id === 'number';
}

/** 更换画风后，哪些已生成的节点画面与新画风不一致：跟随画布风格、已有结果、且没有锁定。 */
export function outdatedNodeIds(nodes: BatchNode[]): string[] {
  return nodes
    .filter((node) => isGenerationNode(node) && !node.data.config?.stale && !node.data.config?.locked && !hasOwnStyle(node.data.config) && isGenerated(node))
    .map((node) => node.id);
}

/** 需要作为"开始前提示选风格"的目标：至少有一个目标节点跟随画布风格。 */
export function anyFollowsCanvasStyle(nodes: BatchNode[], ids: string[]): boolean {
  const wanted = new Set(ids);
  return nodes.some((node) => wanted.has(node.id) && !hasOwnStyle(node.data.config));
}

/** 画风指纹：预设按名称、提示词和参考图，自定义参考图按素材 ID；没有风格为空串。 */
export function styleKeyOfConfig(config: Record<string, unknown> | undefined | null): string {
  const snapshot = config?.style_snapshot as { name?: string; prompt_template?: string; image_url?: string | null } | null | undefined;
  if (snapshot && typeof snapshot === 'object' && Object.keys(snapshot).length) return `preset:${snapshot.name || ''}|${snapshot.prompt_template || ''}|${snapshot.image_url || ''}`;
  if (typeof config?.style_reference_asset_id === 'number') return `ref:${config.style_reference_asset_id}`;
  return '';
}

/** 节点现在应当使用的画风指纹：自己设置了就用自己的；否则跟随画布画风（关闭或没选则为空）。 */
export function effectiveStyleKey(config: Record<string, unknown> | undefined, canvasStyle: CanvasStyle | null): string {
  if (hasOwnStyle(config)) return styleKeyOfConfig(config);
  return styleActive(canvasStyle) ? styleKeyOfConfig(canvasStyle as unknown as Record<string, unknown>) : '';
}

/**
 * 与当前画风不一致的已生成节点：结果来自运行（记录了生成时的画风指纹）、指纹与现在应使用的不同、且没有锁定。
 * 用户上传或固定的素材不算（没有记录，也不该被替换）。
 */
export function inconsistentNodeIds(nodes: BatchNode[], canvasStyle: CanvasStyle | null): string[] {
  return nodes
    .filter((node) => {
      if (!isGenerationNode(node) || node.data.config?.stale || node.data.config?.locked) return false;
      const recorded = node.data.result_style_key;
      const result = node.data.result as { url?: string; reused?: boolean } | undefined;
      if (typeof recorded !== 'string' || !result?.url || result.reused) return false;
      return recorded !== effectiveStyleKey(node.data.config, canvasStyle);
    })
    .map((node) => node.id);
}
