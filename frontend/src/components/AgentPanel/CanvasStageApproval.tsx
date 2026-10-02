import { useState } from 'react';
import type { CanvasAgentApproval, CanvasOpsPreview } from '../../api';
import CanvasPreviewDiff from './CanvasPreviewDiff';
import { CANVAS_STAGE_LABELS } from './canvasAgentMode';

interface Props {
  approval: CanvasAgentApproval;
  disabled: boolean;
  onApprove: () => void;
  onRevise: (suggestion: string) => void;
}

export default function CanvasStageApproval({ approval, disabled, onApprove, onRevise }: Props) {
  const [suggestion, setSuggestion] = useState('');
  const details = approval.parameters.parameters && typeof approval.parameters.parameters === 'object'
    ? approval.parameters.parameters as Record<string, unknown> : approval.parameters;
  const labels: Record<string, string> = { content: '完整剧本', screenplay: '完整剧本', scenes: '场景与节拍', plan: '导演方案', node_ids: '涉及节点', target_node_ids: '执行节点', prompt: '生成提示词', constraints: '创作要求', duration_seconds: '时长（秒）', aspect_ratio: '画面比例', name: '名称', title: '标题', operations: '画布变更', source_node_id: '来源节点' };
  return <section className="mx-3 mb-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-slate-700" aria-label="待确认制作阶段">
    <div className="mb-2 flex items-center justify-between gap-2"><strong>{CANVAS_STAGE_LABELS[approval.stage] || approval.stage || '制作阶段'}</strong><span className="text-xs text-blue-600">待确认</span></div>
    <p className="max-h-44 overflow-y-auto whitespace-pre-wrap text-xs leading-5">{approval.summary || '请查看助手给出的阶段说明后确认。'}</p>
    {approval.preview && <CanvasPreviewDiff preview={approval.preview as CanvasOpsPreview} />}
    {Object.keys(details).length > 0 && <details className="mt-2 rounded-lg border border-blue-100 bg-white p-2"><summary className="cursor-pointer text-xs font-medium text-blue-700">查看完整内容与执行参数</summary><div className="mt-2 max-h-72 space-y-3 overflow-y-auto">{Object.entries(details).map(([key, value]) => <div key={key}><p className="mb-1 text-[11px] font-semibold text-slate-500">{labels[key] || key}</p><pre className="whitespace-pre-wrap break-words font-sans text-xs leading-5">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre></div>)}</div></details>}
    <button type="button" disabled={disabled} onClick={onApprove} className="mt-3 w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{approval.preview ? '确认并应用改动' : '同意，继续此阶段'}</button>
    <textarea aria-label="阶段修改建议" value={suggestion} onChange={event => setSuggestion(event.target.value)} disabled={disabled} placeholder="不满意？告诉助手需要怎样修改…" rows={2} className="mt-3 w-full resize-y rounded-lg border border-blue-200 bg-white p-2 text-xs outline-none focus:border-blue-500" />
    <button type="button" disabled={disabled || !suggestion.trim()} onClick={() => onRevise(suggestion.trim())} className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs text-blue-700 disabled:opacity-40">按建议修改，重新确认</button>
  </section>;
}
