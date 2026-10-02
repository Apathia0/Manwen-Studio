import { describe, expect, it } from 'vitest';
import { canvasPermissionKey, parseCanvasPermissionMode, restoreCanvasActionState, looksLikeConfirmationRequest } from './canvasAgentMode';

describe('画布权限偏好', () => {
  it('缺省及未知值都回退到变更前询问', () => {
    expect(parseCanvasPermissionMode(null)).toBe('ask');
    expect(parseCanvasPermissionMode('unexpected')).toBe('ask');
    expect(parseCanvasPermissionMode('plan')).toBe('ask'); // 计划模式已移除，历史值按询问变更模式处理
    expect(parseCanvasPermissionMode('auto')).toBe('auto');
  });
  it('不同画布与会话使用独立键', () => {
    expect(canvasPermissionKey(1, 2)).not.toBe(canvasPermissionKey(1, 3));
    expect(canvasPermissionKey(1, 2)).not.toBe(canvasPermissionKey(2, 2));
    expect(canvasPermissionKey(1)).not.toBe(canvasPermissionKey(1, 2));
  });
});


describe('恢复阶段授权模式', () => {
  it('待确认动作恢复原计划模式，不受本地默认模式影响', () => {
    const action = { id: 1, canvas_id: 4, stage: 'screenplay', summary: '剧本', parameters: {}, status: 'pending', permission_mode: 'plan' as const };
    expect(restoreCanvasActionState([action], 4)).toMatchObject({ approval: action, mode: 'ask', pendingTask: null });
  });
  it('后台等待以原动作模式续接，同时排除其他画布', () => {
    const task = { canvas_id: 4, run_id: 8, status: 'running' };
    const action = { id: 1, canvas_id: 4, stage: 'videos', summary: '视频', parameters: {}, status: 'waiting', permission_mode: 'ask' as const, result: { pending_task: task } };
    expect(restoreCanvasActionState([action], 4, task)).toMatchObject({ mode: 'ask', pendingTask: { permission_mode: 'ask', run_id: 8 }, approval: null });
    expect(restoreCanvasActionState([action], 5, task)).toMatchObject({ mode: undefined, pendingTask: null, approval: null });
  });
});

describe('文字确认请求识别', () => {
  it('识别回复末尾的确认话术，忽略普通回复', () => {
    expect(looksLikeConfirmationRequest('剧本如上。 --- 请回复确认或修改意见。确认后我会提交阶段。')).toBe(true);
    expect(looksLikeConfirmationRequest('已完成节点修改，共 3 个节点。')).toBe(false);
    expect(looksLikeConfirmationRequest('你告诉我沿用还是重写，我立刻推进。')).toBe(true);
    expect(looksLikeConfirmationRequest('要沿用这个设定吗？')).toBe(true);
    expect(looksLikeConfirmationRequest('请你确认或提出修改点，比如：人物名字。你确认后我会把它作为剧本阶段提案正式提交。 另外提醒：画布还没选画风按钮，建议在顶部确认一下，避免后续画风不一致。')).toBe(true);
    expect(looksLikeConfirmationRequest('')).toBe(false);
  });
});

describe('looksLikeConfirmationRequest', () => {
  it('识别各种“等你确认 / 给意见”的收尾，避免确认卡片漏出', () => {
    expect(looksLikeConfirmationRequest('如果没问题，我就把这份剧本写入画布，由后台继续拆分。')).toBe(true);
    expect(looksLikeConfirmationRequest('你也可以告诉我要改的地方（比如加长到 90 秒）。')).toBe(true);
    expect(looksLikeConfirmationRequest('剧本如上，请回复确认。')).toBe(true);
    expect(looksLikeConfirmationRequest('已完成剧本、拆分和导演编排，请在画布上提交生成。')).toBe(false);
  });
});
