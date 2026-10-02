import { useCallback, useRef, useEffect, useState } from 'react';
import { Check, ChevronDown, Hand, Lightbulb, Paperclip, Rocket, Send, Square, X } from 'lucide-react';
import type { CanvasPermissionMode } from '../../api';
import { CANVAS_PERMISSION_OPTIONS } from './canvasAgentMode';

interface AgentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  streaming?: boolean;
  onStop?: () => void;
  disabled?: boolean;
  placeholder?: string;
  attachments?: File[];
  onAttachmentsChange?: (files: File[]) => void;
  permissionMode?: CanvasPermissionMode;
  permissionModeDisabled?: boolean;
  onPermissionModeChange?: (mode: CanvasPermissionMode) => void;
}

/** 各权限模式在菜单中展示的图标 */
const MODE_ICON: Record<string, typeof Lightbulb> = { plan: Lightbulb, auto: Rocket, ask: Hand };

export default function AgentInput({
  value,
  onChange,
  onSend,
  streaming = false,
  onStop,
  disabled = false,
  placeholder = '输入你的问题…',
  attachments = [],
  onAttachmentsChange,
  permissionMode,
  permissionModeDisabled = false,
  onPermissionModeChange,
}: AgentInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modeMenuRef = useRef<HTMLDivElement>(null);
  const [modeMenuOpen, setModeMenuOpen] = useState(false);

  // 模式菜单：点击外部或按 Esc 收起
  useEffect(() => {
    if (!modeMenuOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (modeMenuRef.current && !modeMenuRef.current.contains(event.target as Node)) setModeMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setModeMenuOpen(false);
    };
    document.addEventListener('pointerdown', handlePointerDown, true);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [modeMenuOpen]);

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    // 助手面板关闭（display:none）时 scrollHeight 为 0，写入 0px 会让输入框没有可点击区域；
    // 此时保持 auto 默认行高，待面板可见后的下一次测量再撑开。
    if (!el.getClientRects().length) return;
    el.style.height = `${el.scrollHeight}px`;
  };

  const handlePaste = useCallback((event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedFiles = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file));
    const supportedFiles = pastedFiles.filter((file) => (
      file.type.startsWith('image/')
      || file.type.startsWith('video/')
      || file.type === 'text/plain'
      || file.type === 'text/markdown'
      || file.type === 'application/pdf'
      || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ));
    if (!supportedFiles.length) return;
    event.preventDefault();
    const available = Math.max(0, 5 - attachments.length);
    const accepted = supportedFiles
      .filter((file) => file.size <= 50 * 1024 * 1024)
      .slice(0, available);
    if (!accepted.length) return;
    const keys = new Set(attachments.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
    const merged = [...attachments];
    accepted.forEach((file) => {
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      if (!keys.has(key)) {
        keys.add(key);
        merged.push(file);
      }
    });
    onAttachmentsChange?.(merged.slice(0, 5));
  }, [attachments, onAttachmentsChange]);

  useEffect(() => {
    if (textareaRef.current) {
      autoResize(textareaRef.current);
    }
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="bg-white rounded-xl px-3 py-2 border border-[#d7e3f4] focus-within:border-blue-400 transition-all">
      {attachments.length > 0 ? <div className="mb-2 flex flex-wrap gap-1">{attachments.map((file, index) => <span key={`${file.name}-${index}`} className="inline-flex items-center gap-1 rounded bg-blue-50 px-2 py-1 text-[11px] text-blue-700">{file.name}<button type="button" onClick={() => onAttachmentsChange?.(attachments.filter((_, i) => i !== index))} title="移除附件"><X size={12} /></button></span>)}</div> : null}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          autoResize(e.target);
        }}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={placeholder}
        disabled={disabled}
        rows={3}
        className="block w-full min-w-0 resize-none bg-transparent px-1.5 py-1 text-sm leading-6 text-gray-700 placeholder-gray-400 outline-none disabled:opacity-50"
        style={{ minHeight: '88px', maxHeight: '240px', overflow: 'auto' }}
      />
      <div ref={modeMenuRef} className="relative mt-1.5 flex items-center justify-between gap-2 border-t border-slate-100 pt-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <label className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-gray-500 hover:bg-blue-50 hover:text-blue-600" title="添加图片或视频">
            <Paperclip size={16} />
            <input type="file" accept="image/*,video/mp4,video/webm,video/quicktime,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" multiple className="hidden" disabled={disabled} onChange={(e) => { onAttachmentsChange?.([...attachments, ...Array.from(e.target.files || [])].slice(0, 5)); e.currentTarget.value = ''; }} />
          </label>
          {permissionMode && (() => {
            const currentMode = CANVAS_PERMISSION_OPTIONS.find(option => option.value === permissionMode);
            const CurrentIcon = MODE_ICON[permissionMode] || Lightbulb;
            return (
              <div className="min-w-0">
                <button
                  type="button"
                  aria-label="画布助手权限模式"
                  aria-haspopup="menu"
                  aria-expanded={modeMenuOpen}
                  title={permissionModeDisabled ? '当前后台阶段沿用原模式，完成后可切换' : '切换权限模式'}
                  disabled={disabled || permissionModeDisabled}
                  onClick={() => setModeMenuOpen(open => !open)}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <CurrentIcon className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{currentMode?.label || permissionMode}</span>
                  <ChevronDown className={`h-3.5 w-3.5 shrink-0 transition-transform ${modeMenuOpen ? 'rotate-180' : ''}`} />
                </button>
                {modeMenuOpen && (
                  <div role="menu" className="absolute bottom-full left-0 right-0 z-30 mb-2 max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_12px_32px_rgba(15,23,42,0.12)]">
                    {CANVAS_PERMISSION_OPTIONS.map(option => {
                      const Icon = MODE_ICON[option.value] || Lightbulb;
                      const active = option.value === permissionMode;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          role="menuitem"
                          onClick={() => { onPermissionModeChange?.(option.value); setModeMenuOpen(false); }}
                          className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition hover:bg-slate-50 ${active ? 'bg-blue-50/70' : ''}`}
                        >
                          <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-md ${active ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'}`}>
                            <Icon className="h-3.5 w-3.5" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
                              {option.label}
                              {active && <Check className="h-3.5 w-3.5 shrink-0 text-blue-600" />}
                            </span>
                            <span className="mt-0.5 block text-[11px] leading-4 text-slate-400">{option.description}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[10px] leading-4 text-slate-400">
            {streaming ? '正在生成…' : permissionModeDisabled ? '当前后台阶段沿用原模式，完成后可切换' : 'Enter 发送 · Shift+Enter 换行'}
          </span>
          {streaming ? (
            <button
              type="button"
              title="停止生成"
              aria-label="停止生成"
              onClick={onStop}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-500 text-white transition hover:bg-red-600"
            >
              <Square size={14} />
            </button>
          ) : (
            <button
              type="button"
              title="发送"
              aria-label="发送"
              onClick={onSend}
              disabled={disabled || (!value.trim() && attachments.length === 0)}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
