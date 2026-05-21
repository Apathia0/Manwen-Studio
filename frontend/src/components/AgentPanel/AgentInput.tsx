import { useRef, useEffect } from 'react';
import { Send } from 'lucide-react';

interface AgentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function AgentInput({
  value,
  onChange,
  onSend,
  disabled = false,
  placeholder = '输入你的问题…',
}: AgentInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  };

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
    <div className="flex items-end gap-2 bg-white rounded-xl px-3 py-2 border border-[#d7e3f4] focus-within:border-blue-400 focus-within:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] transition-all">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          autoResize(e.target);
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        rows={1}
        className="flex-1 bg-transparent text-sm text-gray-700 placeholder-gray-400 resize-none outline-none disabled:opacity-50"
        style={{ maxHeight: '160px', overflow: 'auto' }}
      />
      <button
        onClick={onSend}
        disabled={disabled || !value.trim()}
        className="p-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
      >
        <Send size={16} />
      </button>
    </div>
  );
}
