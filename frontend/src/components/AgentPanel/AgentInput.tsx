import { useCallback, useRef, useEffect } from 'react';
import { Paperclip, Send, X } from 'lucide-react';

interface AgentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
  attachments?: File[];
  onAttachmentsChange?: (files: File[]) => void;
}

export default function AgentInput({
  value,
  onChange,
  onSend,
  disabled = false,
  placeholder = '输入你的问题…',
  attachments = [],
  onAttachmentsChange,
}: AgentInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
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
      <div className="flex items-end gap-2">
      <label className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-gray-500 hover:bg-blue-50 hover:text-blue-600" title="添加图片或视频">
        <Paperclip size={16} />
        <input type="file" accept="image/*,video/mp4,video/webm,video/quicktime,text/plain,text/markdown,application/pdf" multiple className="hidden" disabled={disabled} onChange={(e) => { onAttachmentsChange?.([...attachments, ...Array.from(e.target.files || [])].slice(0, 5)); e.currentTarget.value = ''; }} />
      </label>
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
        rows={1}
        className="flex-1 bg-transparent text-sm text-gray-700 placeholder-gray-400 resize-none outline-none disabled:opacity-50"
        style={{ maxHeight: '160px', overflow: 'auto' }}
      />
      <button
        onClick={onSend}
        disabled={disabled || (!value.trim() && attachments.length === 0)}
        className="p-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
      >
        <Send size={16} />
      </button>
      </div>
    </div>
  );
}
