/**
 * Agent 工具返回值 → 给用户看的一句话。
 *
 * 工具返回的是给模型看的 JSON（整张画布图、校验明细、节点 ID 列表……），绝不能原样展示在聊天里。
 * 这里只提取简短、对用户有意义的信息；提取不到就返回空串，由界面按工具名显示“已完成xx”。
 */

export type ToolResultStatus = 'success' | 'error';

/** 展示给用户的单行摘要上限；超过说明不是一句话，而是被误当成摘要的原始数据 */
export const MAX_TOOL_SUMMARY_CHARS = 120;

/** 看起来像原始 JSON / 数据块而不是一句话 */
export function looksLikeRawData(text: string): boolean {
  const trimmed = text.trim();
  return /^[{[]/.test(trimmed) || /"[A-Za-z_]+"\s*:/.test(trimmed);
}

/** 摘要是否适合直接展示给用户 */
export function isDisplayableSummary(text: string | undefined | null): text is string {
  const value = String(text ?? '').trim();
  return Boolean(value) && value.length <= MAX_TOOL_SUMMARY_CHARS && !looksLikeRawData(value) && !value.includes('\n');
}

function shortText(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : '';
  return isDisplayableSummary(text) ? text : '';
}

function parseResult(raw: unknown): Record<string, unknown> | string | null {
  if (raw === undefined || raw === null) return null;
  if (typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw !== 'string') return String(raw);
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : raw;
  } catch {
    return raw;
  }
}

/** 把一次工具返回整理成 {status, summary}；summary 保证是适合展示的短句或空串 */
export function summarizeToolResult(name: string, raw: unknown): { status: ToolResultStatus; summary: string } {
  const parsed = parseResult(raw);
  if (parsed === null) return { status: 'success', summary: '' };
  if (typeof parsed === 'string') {
    // 非 JSON 的纯文本：短句直接用，长文本不展示
    return { status: 'success', summary: shortText(parsed) };
  }

  if ('error' in parsed && parsed.error) {
    const message = typeof parsed.error === 'string' ? parsed.error : (parsed.error as { message?: unknown })?.message;
    const text = String(message || '执行失败').replace(/\s+/g, ' ').trim();
    return { status: 'error', summary: text.length > MAX_TOOL_SUMMARY_CHARS ? `${text.slice(0, MAX_TOOL_SUMMARY_CHARS)}…` : text };
  }

  if (parsed.awaiting_approval) return { status: 'success', summary: '方案已生成，等待你确认' };
  if (parsed.pending_task) return { status: 'success', summary: '已提交，后台处理中' };
  if (parsed.no_change) return { status: 'success', summary: shortText(parsed.message).replace(/[；;，,].*$/, '') || '没有需要修改的内容' };

  const report = parsed.assets_report as { added?: unknown[]; skipped?: unknown[] } | undefined;
  if (name === 'add_canvas_assets' && report) {
    const added = Array.isArray(report.added) ? report.added.length : 0;
    const skipped = Array.isArray(report.skipped) ? report.skipped.length : 0;
    return { status: 'success', summary: added ? `已补建 ${added} 个资产${skipped ? `，跳过 ${skipped} 个` : ''}` : '没有需要新增的资产' };
  }
  if (name === 'apply_canvas_ops' && typeof parsed.applied_operations === 'number') {
    return { status: 'success', summary: `已修改画布（${parsed.applied_operations} 项操作）` };
  }
  return { status: 'success', summary: shortText(parsed.message) || shortText(parsed.summary) };
}
