/** 画布流水线进度：只从当前节点图与最近一次运行推导，不依赖服务端额外状态。 */

export type PipelineStageKey = 'screenplay' | 'split' | 'director' | 'assets' | 'compile' | 'images' | 'videos' | 'concat';
export type PipelineStageState = 'done' | 'active' | 'next' | 'pending' | 'failed';

export interface PipelineNode {
  id: string;
  type: string;
  data: { config?: Record<string, unknown>; result?: unknown };
}

export interface PipelineRunLike {
  status: string;
  error_message?: string | null;
  nodes?: Array<{ status: string; error_message?: string | null; node_type?: string }>;
}

export interface PipelineStage {
  key: PipelineStageKey;
  label: string;
  state: PipelineStageState;
  /** 该阶段由助手推进（false 表示需要用户在画布上提交生成） */
  byAgent: boolean;
}

export interface PipelineSummary {
  stages: PipelineStage[];
  /** 当前应做的下一阶段；全部完成为 null */
  next: PipelineStage | null;
  failure: string | null;
  pendingImages: number;
  pendingVideos: number;
  /** 尚未生成的节点 id，供一键批量生成使用 */
  pendingAssetIds: string[];
  pendingShotIds: string[];
  pendingVideoIds: string[];
  /** 镜头节点（分镜图和视频）已经编译完成，才允许一键生成 */
  shotsCompiled: boolean;
  /** 场景已拆分但尚未批准，需要用户或全自动模式批准 */
  awaitingSceneApproval: boolean;
}

const LABELS: Record<PipelineStageKey, string> = {
  screenplay: '剧本', split: '拆分', director: '导演', assets: '资产', compile: '分镜', images: '出图', videos: '视频', concat: '合片',
};
const ORDER = Object.keys(LABELS) as PipelineStageKey[];
const AGENT_STAGES = new Set<PipelineStageKey>(['screenplay', 'split', 'director', 'assets', 'compile']);

const cfg = (node: PipelineNode): Record<string, unknown> => node.data.config || {};
const live = (node: PipelineNode) => !cfg(node).stale;
const hasResult = (node: PipelineNode) => Boolean(cfg(node).asset_id) || Boolean((node.data.result as { url?: string } | undefined)?.url);

export function computePipeline(nodes: PipelineNode[], run: PipelineRunLike | null, agentBusy: boolean): PipelineSummary {
  const active = nodes.filter(live);
  const screenplay = active.filter((n) => n.type === 'screenplay' && String(cfg(n).content ?? cfg(n).screenplay ?? '').trim());
  const scenes = active.filter((n) => n.type === 'scene');
  const approved = scenes.length > 0 && scenes.every((n) => Boolean(cfg(n).approved));
  const planned = scenes.length > 0 && scenes.every((n) => Boolean(cfg(n).director_plan));
  const assets = active.filter((n) => n.type === 'image' && ['character', 'scene', 'prop'].includes(String(cfg(n).asset_role || '')));
  const storyboards = active.filter((n) => n.type === 'image' && cfg(n).node_role === 'storyboard');
  const videos = active.filter((n) => n.type === 'video' && cfg(n).source_scene_node);
  const concat = active.filter((n) => n.type === 'concat');

  const done: Record<PipelineStageKey, boolean> = {
    screenplay: screenplay.length > 0,
    split: scenes.length > 0,
    director: planned,
    assets: assets.length > 0,
    compile: storyboards.length > 0 && videos.length > 0,
    images: storyboards.length > 0 && storyboards.every(hasResult),
    videos: videos.length > 0 && videos.every(hasResult),
    concat: concat.some(hasResult),
  };

  const failedRunNode = run?.status === 'failed' ? (run.nodes || []).find((n) => n.status === 'failed') : undefined;
  const failure = run?.status === 'failed' ? (failedRunNode?.error_message || run.error_message || '上一次生成任务失败') : null;
  const failedStage: PipelineStageKey | null = failure
    ? (failedRunNode?.node_type === 'video' ? 'videos' : failedRunNode?.node_type === 'concat' ? 'concat' : 'images')
    : null;

  let nextKey: PipelineStageKey | null = null;
  const stages: PipelineStage[] = ORDER.map((key) => {
    let state: PipelineStageState;
    if (failedStage === key && !done[key]) state = 'failed';
    else if (done[key]) state = 'done';
    else if (nextKey === null) { nextKey = key; state = agentBusy && AGENT_STAGES.has(key) ? 'active' : 'next'; }
    else state = 'pending';
    return { key, label: LABELS[key], state, byAgent: AGENT_STAGES.has(key) };
  });

  return {
    stages,
    next: stages.find((s) => s.key === nextKey) || null,
    failure,
    pendingImages: storyboards.filter((n) => !hasResult(n)).length + assets.filter((n) => !hasResult(n)).length,
    pendingVideos: videos.filter((n) => !hasResult(n)).length,
    pendingAssetIds: assets.filter((n) => !hasResult(n)).map((n) => n.id),
    pendingShotIds: storyboards.filter((n) => !hasResult(n)).map((n) => n.id),
    pendingVideoIds: videos.filter((n) => !hasResult(n)).map((n) => n.id),
    shotsCompiled: done.compile,
    awaitingSceneApproval: scenes.length > 0 && !approved,
  };
}

/** 继续某一助手阶段时发给助手的指令（全自动模式下会一路推进到分镜节点）。 */
export function continuePrompt(stage: PipelineStageKey): string {
  const text: Partial<Record<PipelineStageKey, string>> = {
    screenplay: '请根据我的想法创作剧本并写入画布。',
    split: '请继续：拆分当前剧本。',
    director: '请继续：对已批准的场景进行导演编排。',
    assets: '请继续：提取角色、场景和道具资产。',
    compile: '请继续：把导演方案编译为分镜和视频节点。',
  };
  return text[stage] || '继续';
}

/** 成本预估的一行摘要：积分模式显示预估与余额，自带 Key 模式显示数量与时长。 */
export function formatCostLine(cost: {
  credential_mode: string; image_count: number; video_count: number; video_seconds: number;
  total_points: number | null; available_points: number | null; sufficient: boolean | null; warnings?: string[];
}): string {
  const amount = `图片 ${cost.image_count} 张 · 视频 ${cost.video_count} 条（${Math.round(cost.video_seconds)} 秒）`;
  if (cost.credential_mode !== 'platform' || cost.total_points === null) return `待生成：${amount} · 使用自有 API Key，费用由服务商结算`;
  const points = `${Number(cost.total_points.toFixed(2))} 积分`;
  const note = cost.warnings && cost.warnings.length ? '（部分模型无法预估）' : '';
  if (cost.sufficient === false && cost.available_points !== null) return `待生成：${amount} · 预估 ${points}${note}，余额 ${Number(cost.available_points.toFixed(2))} 不足`;
  return `待生成：${amount} · 预估 ${points}${note}${cost.available_points !== null ? `，余额 ${Number(cost.available_points.toFixed(2))}` : ''}`;
}

/** "再生成一个"按钮上的花费提示。 */
export function formatRegenerateCost(cost: { credential_mode: string; total_points: number | null; image_count: number; video_count: number; video_seconds: number }): string {
  if (cost.credential_mode !== 'platform' || cost.total_points === null) return '自有 API Key';
  const upstream = cost.image_count + cost.video_count;
  return `约 ${Number(cost.total_points.toFixed(2))} 积分${upstream > 1 ? `，含上游 ${upstream - 1} 个节点` : ''}`;
}
