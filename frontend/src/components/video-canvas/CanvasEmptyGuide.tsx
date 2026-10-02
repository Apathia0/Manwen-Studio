import { useState } from 'react';
import { FileText, Sparkles } from 'lucide-react';
import type { CanvasPermissionMode, VideoStylePreset } from '../../api';
import { canvasPermissionKey, parseCanvasPermissionMode } from '../AgentPanel/canvasAgentMode';
import { CANVAS_TEMPLATES, ideaPrompt } from './canvasTemplates';
import StyleControl from './StyleControl';
import { styleActive, styleDisplay, type CanvasStyle } from './canvasStyle';

interface Props {
  canvasId: number;
  /** 把指令交给 AI 助手并立即发送；mode 是开场选定的助手工作模式 */
  onSend: (prompt: string, mode: CanvasPermissionMode) => void;
  /** 导入小说章节；mode 是开场选定的助手工作方式，导入完成后据此自动开启编排 */
  onImportChapter: (mode: CanvasPermissionMode) => void;
  /** 开局选画风：整张画布统一的画风 */
  style: CanvasStyle | null;
  presets: VideoStylePreset[];
  onPickPreset: (preset: VideoStylePreset) => void;
  onOpenStyleModal: () => void;
  onToggleStyle: (enabled: boolean) => void;
  /** 开局选画面比例：整部作品的图片、视频节点统一使用，单个节点之后仍可手动改 */
  aspect: string;
  onPickAspect: (aspect: string) => void;
  /** 开局选分镜时长：flexible 灵活剪切（4~15 秒）/ fixed15 固定 15 秒（视频模型只支持 15 秒时用） */
  shotMode: ShotDurationMode;
  onPickShotMode: (mode: ShotDurationMode) => void;
}

export type ShotDurationMode = 'flexible' | 'fixed15';

const SHOT_MODE_OPTIONS: Array<{ value: ShotDurationMode; title: string; desc: string }> = [
  { value: 'flexible', title: '灵活剪切', desc: '按剧情节奏 4~15 秒，镜头更利落，也更省视频费用' },
  { value: 'fixed15', title: '固定 15 秒', desc: '适合只支持 15 秒的视频模型；按内容量装满，不靠拖沓凑时长' },
];

const ASPECT_OPTIONS = [
  { value: '16:9', label: '横屏', w: 20, h: 12 },
  { value: '9:16', label: '竖屏', w: 12, h: 20 },
  { value: '1:1', label: '方形', w: 16, h: 16 },
  { value: '4:3', label: '4:3', w: 18, h: 14 },
  { value: '3:4', label: '3:4', w: 14, h: 18 },
];

/** 空画布引导：一句话创意、题材模板、导入小说三条起步路径。 */
export default function CanvasEmptyGuide({ canvasId, onSend, onImportChapter, style, presets, onPickPreset, onOpenStyleModal, onToggleStyle, aspect, onPickAspect, shotMode, onPickShotMode }: Props) {
  const [idea, setIdea] = useState('');
  const [mode, setMode] = useState<CanvasPermissionMode>(() => {
    try { const saved = localStorage.getItem(canvasPermissionKey(canvasId)); return saved ? parseCanvasPermissionMode(saved) : 'auto'; } catch { return 'auto'; }
  });
  const styleName = styleActive(style) ? styleDisplay(style).name : '';
  const send = (prompt: string) => onSend(`${prompt}${styleName ? `画风：${styleName}。` : ''}画面比例：${aspect}。${shotMode === 'fixed15' ? '分镜时长：每个视频固定15秒（视频模型只支持15秒），请把每场戏写成约15秒的内容量（约80字），每一拍都推进剧情，不要靠重复动作拖时长。' : ''}`, mode);
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
      <div className="compact-controls pointer-events-auto w-full max-w-[560px] rounded-2xl border border-[#393633] bg-[#211f1d]/95 p-5 shadow-2xl">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#f0ebde]"><Sparkles className="h-4 w-4 text-[#f3cf84]" />三步开始你的漫剧</div>
        <p className="mb-3 text-xs text-[#a79f98]">写一句创意，AI 助手会自动完成剧本、拆分、导演编排、资产和分镜节点。你检查满意后，再自己提交出图和视频生成。</p>
        <div className="mb-3 rounded-xl border border-[#393633] bg-[#171513] p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#e1ddd9]">先选画风 <span className="font-normal text-[#8f8984]">整部作品的画面保持统一，之后可随时调整</span></span>
            <StyleControl style={style} onPick={onOpenStyleModal} onToggle={onToggleStyle} />
          </div>
          {!style && presets.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {presets.slice(0, 6).map((preset) => (
                <button key={preset.id} type="button" onClick={() => onPickPreset(preset)} className="rounded-full border border-[#4a4540] px-2.5 py-1 text-[11px] text-[#e1ddd9] hover:border-[#73a7ff]">{preset.name}</button>
              ))}
              <button type="button" onClick={onOpenStyleModal} className="rounded-full border border-dashed border-[#4a4540] px-2.5 py-1 text-[11px] text-[#c9c1ba] hover:border-[#73a7ff]">更多 / 上传参考图</button>
            </div>
          )}
        </div>
        <div className="mb-3 rounded-xl border border-[#393633] bg-[#171513] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#e1ddd9]">画面比例 <span className="font-normal text-[#8f8984]">所有图片和视频默认沿用，单个节点之后仍可单独改</span></span>
            <div className="flex gap-1.5" role="radiogroup" aria-label="画面比例">
              {ASPECT_OPTIONS.map((option) => (
                <button key={option.value} type="button" role="radio" aria-checked={aspect === option.value} onClick={() => onPickAspect(option.value)} title={`${option.value} ${option.label}`}
                  className={`flex h-12 w-14 flex-col items-center justify-center gap-1 rounded-lg border text-[10px] transition ${aspect === option.value ? 'border-[#73a7ff] bg-[#73a7ff]/10 text-[#9fc2ff]' : 'border-[#4a4540] text-[#a79f98] hover:border-[#73a7ff]'}`}>
                  <span className="rounded-[2px] border border-current" style={{ width: option.w, height: option.h }} />
                  {option.value}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="mb-3 rounded-xl border border-[#393633] bg-[#171513] p-3">
          <div className="mb-2 text-xs font-medium text-[#e1ddd9]">分镜时长 <span className="font-normal text-[#8f8984]">导演拆分镜头时按它控制每个视频的时长</span></div>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="分镜时长">
            {SHOT_MODE_OPTIONS.map((option) => (
              <button key={option.value} type="button" role="radio" aria-checked={shotMode === option.value} onClick={() => onPickShotMode(option.value)}
                className={`rounded-lg border p-2.5 text-left transition ${shotMode === option.value ? 'border-[#73a7ff] bg-[#73a7ff]/10' : 'border-[#4a4540] hover:border-[#73a7ff]'}`}>
                <div className={`text-xs font-medium ${shotMode === option.value ? 'text-[#9fc2ff]' : 'text-[#e1ddd9]'}`}>{option.title}</div>
                <div className="mt-0.5 text-[11px] text-[#8b837c]">{option.desc}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="mb-3 rounded-xl border border-[#393633] bg-[#171513] p-3">
          <div className="mb-2 text-xs font-medium text-[#e1ddd9]">助手工作方式 <span className="font-normal text-[#8f8984]">之后可在助手输入框左下角随时切换</span></div>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="助手工作方式">
            {([
              { value: 'auto' as const, title: '自动模式', desc: '一路自动编排到节点完整，中途不再询问' },
              { value: 'ask' as const, title: '询问变更模式', desc: '每个阶段先给你看方案，确认后才执行' },
            ]).map((option) => (
              <button key={option.value} type="button" role="radio" aria-checked={mode === option.value} onClick={() => setMode(option.value)}
                className={`rounded-lg border p-2.5 text-left transition ${mode === option.value ? 'border-[#73a7ff] bg-[#73a7ff]/10' : 'border-[#4a4540] hover:border-[#73a7ff]'}`}>
                <div className={`text-xs font-medium ${mode === option.value ? 'text-[#9fc2ff]' : 'text-[#e1ddd9]'}`}>{option.title}</div>
                <div className="mt-0.5 text-[11px] text-[#8b837c]">{option.desc}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <input
            value={idea}
            maxLength={200}
            onChange={(event) => setIdea(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter' && idea.trim()) send(ideaPrompt(idea)); }}
            placeholder="例如：雨夜，分手三年的两个人因为一把伞重逢"
            className="min-w-0 flex-1 rounded-lg border border-[#4a4540] bg-[#171513] px-3 py-2 text-sm text-white outline-none placeholder:text-[#6f6862] focus:border-[#73a7ff]"
            aria-label="一句话创意"
          />
          <button type="button" disabled={!idea.trim()} onClick={() => send(ideaPrompt(idea))} className="rounded-lg bg-[#73a7ff] px-4 text-sm font-medium text-[#111827] hover:bg-[#8db6ff] disabled:cursor-not-allowed disabled:opacity-40">开始创作</button>
        </div>
        <div className="mt-4 text-xs text-[#a79f98]">或选一个题材模板</div>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {CANVAS_TEMPLATES.map((template) => (
            <button key={template.id} type="button" onClick={() => send(template.prompt)} className="rounded-lg border border-[#393633] bg-[#171513] p-2.5 text-left transition hover:border-[#73a7ff]">
              <div className="text-xs font-medium text-[#f0ebde]">{template.title}</div>
              <div className="mt-0.5 text-[11px] text-[#8b837c]">{template.desc}</div>
            </button>
          ))}
          <button type="button" onClick={() => onImportChapter(mode)} className="flex items-center gap-2 rounded-lg border border-dashed border-[#4a4540] p-2.5 text-left text-xs text-[#c9c1ba] transition hover:border-[#73a7ff]">
            <FileText className="h-4 w-4 shrink-0" />导入小说章节
          </button>
        </div>
      </div>
    </div>
  );
}
