import type { CanvasPermissionMode, CanvasAgentApproval, CanvasAgentPendingTask } from '../../api';

export const CANVAS_PERMISSION_OPTIONS: Array<{ value: CanvasPermissionMode; label: string; description: string }> = [
  { value: 'auto', label: '自动模式', description: '一路自动编排到节点完整，中途不再询问' },
  { value: 'ask', label: '询问变更模式', description: '每个阶段先给你看方案，确认后才执行' },
];

export function parseCanvasPermissionMode(value: string | null): CanvasPermissionMode {
  // 计划模式已移除：历史上保存的 plan 一律按“询问变更模式”处理
  return value === 'auto' ? value : 'ask';
}

export function canvasPermissionKey(canvasId: number, conversationId?: number | null): string {
  return `storycanvas.agent-mode.${canvasId}.${conversationId ?? 'default'}`;
}

export const CANVAS_STAGE_LABELS: Record<string, string> = {
  screenplay: '编写剧本', split: '拆分场景', director: '导演编排', assets: '准备角色与场景资产',
  compile: '生成镜头节点', images: '生成分镜图片', videos: '生成视频片段', concat: '制作成片',
  graph: '修改画布', apply_canvas_ops: '修改画布',
};

/** 恢复服务端授权模式，不用本地偏好替换在途动作的授权。 */
export function restoreCanvasActionState(actions: CanvasAgentApproval[], canvasId: number, task?: CanvasAgentPendingTask | null) {
  const owned = actions.filter(action => !action.canvas_id || action.canvas_id === canvasId);
  const pendingTask = task?.canvas_id === canvasId ? task : null;
  const waitingAction = pendingTask ? owned.find(action => action.status === 'waiting' && action.result?.pending_task?.run_id === pendingTask.run_id) : undefined;
  const approval = pendingTask ? null : owned.find(action => action.status === 'pending') || null;
  const rawMode = waitingAction?.permission_mode || pendingTask?.permission_mode || approval?.permission_mode;
  const mode = rawMode ? parseCanvasPermissionMode(rawMode) : undefined;
  return { approval, pendingTask: pendingTask ? { ...pendingTask, permission_mode: mode } : null, mode };
}

/** 助手回复末尾是否在文字里请求用户确认/给意见（此时没有结构化提案卡片，需由前端补一张确认卡）。 */
export function looksLikeConfirmationRequest(text: string | undefined | null): boolean {
  // 回复末尾常跟一段“另外提醒”之类的补充，所以看最后 400 字而不是只看最后一句。
  const tail = String(text || '').trim().slice(-400);
  if (!tail) return false;
  // 明确的确认话术，或“告诉我…推进/继续/重写/修改”这类等待用户决定的收尾，或以问句结尾。
  return /(请回复确认|回复确认|请.{0,3}确认|你确认|确认或提出|是否确认|修改意见|提出.{0,6}(修改|意见)|修改点|是否满意|满意的话|请告知是否|告诉我.{0,16}(推进|继续|重写|修改|调整)|如果(没问题|没有问题|满意|可以|确认无误|你同意)|你也可以告诉我|告诉我(你|要|哪)|要改的地方|需要(改|调整)的地方|我(就|再)(把|开始|继续|写入)|[?？]$)/.test(tail);
}
