import { useState } from 'react';

interface Props {
  disabled: boolean;
  onConfirm: () => void;
  onRevise: (suggestion: string) => void;
}

/** 助手在文字回复末尾请求确认时的快捷卡片：一键确认继续，或填写修改意见。 */
export default function CanvasReplyConfirm({ disabled, onConfirm, onRevise }: Props) {
  const [suggestion, setSuggestion] = useState('');
  return <section className="mx-3 mb-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-slate-700" aria-label="待确认回复">
    <div className="mb-2 flex items-center justify-between gap-2"><strong>确认方案</strong><span className="text-xs text-blue-600">待确认</span></div>
    <button type="button" disabled={disabled} onClick={onConfirm} className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">同意，继续下一步</button>
    <textarea aria-label="修改意见" value={suggestion} onChange={event => setSuggestion(event.target.value)} disabled={disabled} placeholder="不满意？告诉助手需要怎样修改…" rows={2} className="mt-3 w-full resize-y rounded-lg border border-blue-200 bg-white p-2 text-xs outline-none focus:border-blue-500" />
    <button type="button" disabled={disabled || !suggestion.trim()} onClick={() => { onRevise(suggestion.trim()); setSuggestion(''); }} className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs text-blue-700 disabled:opacity-40">按建议修改，重新确认</button>
  </section>;
}
