import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, X } from 'lucide-react';
import type { VideoStylePreset } from '../../api';
import { styleDisplay, type CanvasStyle } from './canvasStyle';
import StyleControl from './StyleControl';

export interface BatchStartInfo {
  /** 将要生成的节点数与批次数 */
  total: number;
  waves: number;
  /** 因依赖而自动加入的上游节点数 */
  added: number;
  /** 重新生成（而不是补生成）已有结果的节点数 */
  regenerate: boolean;
  /** 预估花费摘要，例如"图片 3 张 · 视频 2 条 · 预估 12 积分，余额 30" */
  costLine: string | null;
  costWarnings: string[];
  /** 是否有目标节点跟随画布风格（都自带风格时不需要提示选风格） */
  needsStyle: boolean;
}

interface Props {
  info: BatchStartInfo;
  style: CanvasStyle | null;
  presets: VideoStylePreset[];
  onPickPreset: (preset: VideoStylePreset) => void;
  onOpenStyleModal: () => void;
  onToggleStyle: (enabled: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * 批量生成开始前的确认：一处看清数量、花费，并在这里就地选择画风——
 * 没选画风时给出醒目提示和几个常用预设，一键选好再开始，避免生成完才发现画风不统一。
 */
export default function BatchStartDialog({ info, style, presets, onPickPreset, onOpenStyleModal, onToggleStyle, onConfirm, onCancel }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const quick = presets.slice(0, 4);
  const { name, enabled } = styleDisplay(style);
  const active = Boolean(style && enabled);
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="确认批量生成" className="compact-controls fixed inset-0 z-[90] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onCancel}>
      <div className="w-full max-w-[460px] rounded-2xl border border-[#393633] bg-[#211f1d] p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <div className="text-base font-semibold text-[#f0ebde]">{info.regenerate ? '确认按新画风重新生成' : '确认批量生成'}</div>
            <div className="mt-1 text-xs text-[#a79f98]">
              {info.regenerate ? '将重新生成' : '将生成'} {info.total} 个节点，分 {info.waves} 批，同一批内并行
              {info.added > 0 && `；已自动加入 ${info.added} 个尚未生成的上游节点`}
            </div>
          </div>
          <button type="button" aria-label="关闭" onClick={onCancel} className="rounded-md p-1 text-[#958d86] hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></button>
        </div>

        {info.needsStyle && (
          <div className={`mt-4 rounded-xl border p-3 ${active ? 'border-[#393633] bg-[#171513]' : 'border-amber-400/40 bg-amber-400/10'}`}>
            <div className="flex items-center justify-between gap-2">
              <span className={`text-xs font-medium ${active ? 'text-[#e1ddd9]' : 'text-amber-200'}`}>{active ? '本次使用的画风' : style ? '全局画风已关闭' : '还没有选择画风'}</span>
              <StyleControl style={style} onPick={onOpenStyleModal} onToggle={onToggleStyle} />
            </div>
            <p className="mt-1.5 text-[11px] leading-4 text-[#a79f98]">
              {active
                ? `所有未单独设置风格的资产、分镜和视频都会使用「${name}」，画面保持统一。`
                : style
                  ? `「${name}」已保留但没有开启，这次生成不会使用它。打开右侧开关即可应用。`
                  : '不选画风时，每张图会各自发挥，角色和场景的画风很容易前后不一致。建议先选一个：'}
            </p>
            {!style && quick.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {quick.map((preset) => (
                  <button key={preset.id} type="button" onClick={() => onPickPreset(preset)} className="rounded-full border border-[#4a4540] px-2.5 py-1 text-[11px] text-[#e1ddd9] hover:border-[#73a7ff]">{preset.name}</button>
                ))}
                <button type="button" onClick={onOpenStyleModal} className="rounded-full border border-dashed border-[#4a4540] px-2.5 py-1 text-[11px] text-[#c9c1ba] hover:border-[#73a7ff]">更多 / 上传参考图</button>
              </div>
            )}
          </div>
        )}

        {info.costLine && (
          <div className="mt-3 text-xs text-[#c9c1ba]">{info.costLine}。已生成且未修改的节点会自动复用，不重复计费。</div>
        )}
        {info.costWarnings.length > 0 && (
          <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-4 text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{info.costWarnings[0]}{info.costWarnings.length > 1 && `（另有 ${info.costWarnings.length - 1} 条提示）`}</span>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-[#4a4540] px-4 py-2 text-xs text-[#e1ddd9] hover:bg-white/5">取消</button>
          <button type="button" onClick={onConfirm} className="rounded-lg bg-[#73a7ff] px-4 py-2 text-xs font-semibold text-[#111827] hover:bg-[#8db6ff]">
            {info.needsStyle && !active ? '不使用画风，直接生成' : '开始生成'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
