import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { agentChatStream, getCanvasAgentActions, type CanvasAgentApproval } from './api';

describe('画布 Agent 阶段协议', () => {
  beforeEach(() => { vi.stubGlobal('localStorage', { getItem: () => null }); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('提交明确模式与审批 ID，分别接收审批和等待事件', async () => {
    const approval: CanvasAgentApproval = { id: 7, stage: 'images', summary: '生成已审核镜头的分镜图', parameters: {}, status: 'pending' };
    const task = { canvas_id: 4, run_id: 9, status: 'running' };
    const body = `event: stage_pending\ndata: ${JSON.stringify({ approval })}\n\nevent: waiting\ndata: ${JSON.stringify({ pending_task: task })}\n\nevent: done\ndata: {"content":"阶段已准备"}\n\n`;
    const fetchMock = vi.fn(async () => new Response(body, { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const onStagePending = vi.fn();
    const onWaiting = vi.fn();
    await new Promise<void>((resolve, reject) => {
      agentChatStream(1, 2, '继续', undefined, 'video_canvas', 4, undefined, undefined, undefined,
        { onStagePending, onWaiting, onDone: () => resolve(), onError: error => reject(new Error(error.message)) },
        { canvas_permission_mode: 'plan', canvas_approval_id: 7 });
    });
    const request = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(request[1].body))).toMatchObject({ canvas_permission_mode: 'plan', canvas_approval_id: 7, workflow_id: 4 });
    expect(onStagePending).toHaveBeenCalledWith(approval);
    expect(onWaiting).toHaveBeenCalledWith(task);
  });

  it('video_canvas 请求携带浏览器实时画布快照，其他工作流不携带', async () => {
    const fetchMock = vi.fn(async () => new Response('event: done\ndata: {"content":"完成"}\n\n'));
    vi.stubGlobal('fetch', fetchMock);
    const graph = { schema_version: 1, nodes: [{ id: 'image-1', type: 'image', position: { x: 10, y: 20 }, data: { label: '当前图片', config: {} } }], edges: [], groups: [], metadata: {} };
    for (const workflow of ['video_canvas', 'novel']) {
      await new Promise<void>((resolve, reject) => agentChatStream(1, 2, '读取当前图', undefined, workflow, 4, undefined, undefined, undefined,
        { onDone: () => resolve(), onError: error => reject(new Error(error.message)) },
        { canvas_graph: graph }));
    }
    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(JSON.parse(String(calls[0][1].body))).toMatchObject({ canvas_graph: graph });
    expect(JSON.parse(String(calls[1][1].body))).not.toHaveProperty('canvas_graph');
  });

  it('续接使用独立运行 ID，其他工作流不发送画布权限字段', async () => {
    const fetchMock = vi.fn(async () => new Response('event: done\ndata: {"content":"完成"}\n\n'));
    vi.stubGlobal('fetch', fetchMock);
    for (const workflow of ['video_canvas', 'novel']) {
      await new Promise<void>((resolve, reject) => agentChatStream(1, 2, '继续', undefined, workflow, 4, undefined, undefined, undefined,
        { onDone: () => resolve(), onError: error => reject(new Error(error.message)) },
        { canvas_permission_mode: 'auto', canvas_resume_run_id: 9, canvas_revision_approval_id: 3 }));
    }
    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(JSON.parse(String(calls[0][1].body))).toMatchObject({ canvas_permission_mode: 'auto', canvas_resume_run_id: 9, canvas_revision_approval_id: 3 });
    expect(JSON.parse(String(calls[1][1].body))).not.toHaveProperty('canvas_permission_mode');
  });

  it('重开会话可恢复待确认动作及等待任务', async () => {
    const result = { actions: [], pending_task: { canvas_id: 4, run_id: 9, status: 'running' } };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(result)));
    vi.stubGlobal('fetch', fetchMock);
    await expect(getCanvasAgentActions(1, 2)).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith('/api/stories/1/agent/canvas-actions?conversation_id=2', expect.any(Object));
  });
});
