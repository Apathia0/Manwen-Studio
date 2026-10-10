import { describe, expect, it } from 'vitest';
import { isDisplayableSummary, summarizeToolResult } from './agentToolSummary';

const HUGE = JSON.stringify({
  ok: true, definition_revision: 9, applied_operations: 4,
  graph: { nodes: Array.from({ length: 40 }, (_, i) => ({ id: `image-${i}`, type: 'image' })), edges: [] },
  validation: { errors: [], warnings: [], topological_order: ['a', 'b'] },
});

describe('summarizeToolResult', () => {
  it('成功结果里的整张图 / 校验明细绝不会变成摘要', () => {
    const { status, summary } = summarizeToolResult('apply_canvas_ops', HUGE);
    expect(status).toBe('success');
    expect(summary).toBe('已修改画布（4 项操作）');
    expect(summary).not.toContain('{');
  });

  it('提取不到人话时返回空串，由界面按工具名显示', () => {
    expect(summarizeToolResult('get_canvas_outline', JSON.stringify({ nodes: [{ id: 'a' }], counts: { image: 3 } })).summary).toBe('');
    expect(summarizeToolResult('canvas_stage', JSON.stringify({ ok: true, stage: 'compile', node_ids: ['x'] })).summary).toBe('');
  });

  it('错误取 error 文本，过长会截断', () => {
    expect(summarizeToolResult('x', JSON.stringify({ error: '画布已更新，请重试' }))).toEqual({ status: 'error', summary: '画布已更新，请重试' });
    const long = summarizeToolResult('x', JSON.stringify({ error: '错'.repeat(400) }));
    expect(long.status).toBe('error');
    expect(long.summary.length).toBeLessThanOrEqual(121);
  });

  it('待确认 / 后台处理 / 无变化 / 补建资产都有简短说明', () => {
    expect(summarizeToolResult('apply_canvas_ops', JSON.stringify({ awaiting_approval: true, approval: { id: 1 } })).summary).toBe('方案已生成，等待你确认');
    expect(summarizeToolResult('canvas_stage', JSON.stringify({ pending_task: { run_id: 1 } })).summary).toBe('已提交，后台处理中');
    expect(summarizeToolResult('apply_canvas_ops', JSON.stringify({ ok: true, no_change: true, message: '这些改动已经在画布上，无需重复提交；请继续其它步骤' })).summary).toBe('这些改动已经在画布上');
    expect(summarizeToolResult('add_canvas_assets', JSON.stringify({ ok: true, assets_report: { added: [{}, {}], skipped: [{}] } })).summary).toBe('已补建 2 个资产，跳过 1 个');
  });

  it('纯文本只在是短句时保留', () => {
    expect(summarizeToolResult('x', '已保存').summary).toBe('已保存');
    expect(summarizeToolResult('x', '很长'.repeat(100)).summary).toBe('');
    expect(summarizeToolResult('x', undefined)).toEqual({ status: 'success', summary: '' });
  });
});

describe('isDisplayableSummary', () => {
  it('拒绝 JSON 片段、多行与超长文本', () => {
    expect(isDisplayableSummary('已完成')).toBe(true);
    expect(isDisplayableSummary('{"ok": true}')).toBe(false);
    expect(isDisplayableSummary('"warnings": [], "errors": []')).toBe(false);
    expect(isDisplayableSummary('第一行\n第二行')).toBe(false);
    expect(isDisplayableSummary('长'.repeat(200))).toBe(false);
    expect(isDisplayableSummary('')).toBe(false);
  });
});
