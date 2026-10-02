import { describe, expect, it } from 'vitest';
import type { CanvasAgentRequestOptions, VideoCanvasGraph } from '../../api';
import { buildCanvasAgentEffectiveOptions, buildCanvasChatOptions } from './AgentPanel';

const emptyGraph: VideoCanvasGraph = { schema_version: 1, nodes: [], edges: [] };

describe('修订提案 ID 只随当前请求携带一次', () => {
  it('取用后立即清空引用，后续调用不再附带', () => {
    const ref = { current: 42 };
    const first = buildCanvasAgentEffectiveOptions(ref);
    expect(first.canvas_revision_approval_id).toBe(42);
    // 取用即清：第二次调用不得再携带旧提案 ID，避免附带到后续消息触发 revise 409
    expect(ref.current).toBeUndefined();
    const second = buildCanvasAgentEffectiveOptions(ref);
    expect(second.canvas_revision_approval_id).toBeUndefined();
  });

  it('显式 requestOptions 中的修订 ID 优先于 ref 中的旧值', () => {
    const ref = { current: 1 };
    const requestOptions: CanvasAgentRequestOptions = { canvas_revision_approval_id: 2, canvas_approval_id: 7 };
    const merged = buildCanvasAgentEffectiveOptions(ref, requestOptions);
    expect(merged.canvas_revision_approval_id).toBe(2);
    expect(merged.canvas_approval_id).toBe(7);
    expect(ref.current).toBeUndefined();
  });

  it('空 ref 时不注入 canvas_revision_approval_id 字段', () => {
    const ref = { current: undefined };
    const merged = buildCanvasAgentEffectiveOptions(ref, { canvas_resume_run_id: 9 });
    expect('canvas_revision_approval_id' in merged).toBe(false);
    expect(merged.canvas_resume_run_id).toBe(9);
  });
});

describe('画布 Agent 请求选项组装', () => {
  it('写入模式默认 server，并透传权限、图快照与客户端修订号', () => {
    const options = buildCanvasChatOptions('auto', { canvas_approval_id: 3 }, emptyGraph, 11);
    expect(options.canvas_graph_write_mode).toBe('server');
    expect(options.canvas_permission_mode).toBe('auto');
    expect(options.canvas_approval_id).toBe(3);
    expect(options.canvas_graph).toBe(emptyGraph);
    expect(options.canvas_client_revision).toBe(11);
  });

  it('选中的节点 ID 随请求上送，未选中时不携带字段，并限制数量', () => {
    const selected = buildCanvasChatOptions('ask', {}, emptyGraph, 1, ['a', 'b']);
    expect(selected.canvas_selected_node_ids).toEqual(['a', 'b']);
    expect('canvas_selected_node_ids' in buildCanvasChatOptions('ask', {}, emptyGraph, 1, [])).toBe(false);
    expect('canvas_selected_node_ids' in buildCanvasChatOptions('ask', {}, emptyGraph, 1)).toBe(false);
    const many = Array.from({ length: 30 }, (_, index) => `n${index}`);
    expect(buildCanvasChatOptions('ask', {}, emptyGraph, 1, many).canvas_selected_node_ids).toHaveLength(20);
  });

  it('effectiveOptions 中的修订 ID 不被权限字段覆盖', () => {
    const options = buildCanvasChatOptions('plan', { canvas_revision_approval_id: 5 }, undefined, 0);
    expect(options.canvas_revision_approval_id).toBe(5);
    expect(options.canvas_permission_mode).toBe('plan');
  });
});
