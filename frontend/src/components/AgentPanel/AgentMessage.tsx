import type { AgentMessageData } from './AgentPanel';
import ToolCallStatus from './ToolCallStatus';
import { Bot, User } from 'lucide-react';

interface AgentMessageProps {
  message: AgentMessageData;
}

function 渲染消息内容(content: string) {
  const parts = content.split(/(```[\s\S]*?```)/g);
  return parts.map((part, index) => {
    if (part.startsWith('```') && part.endsWith('```')) {
      const codeContent = part.slice(3, -3).replace(/^\w+\n/, '');
      return (
        <pre
          key={index}
          className="my-2 p-3 bg-gray-900 rounded-lg overflow-x-auto text-xs leading-relaxed text-gray-200 font-mono"
        >
          <code>{codeContent}</code>
        </pre>
      );
    }
    const inlineParts = part.split(/(`[^`]+`)/g);
    return (
      <span key={index}>
        {inlineParts.map((seg, si) => {
          if (seg.startsWith('`') && seg.endsWith('`')) {
            return (
              <code
                key={si}
                className="px-1 py-0.5 bg-blue-100 rounded text-xs text-blue-700 font-mono"
              >
                {seg.slice(1, -1)}
              </code>
            );
          }
          return seg;
        })}
      </span>
    );
  });
}

export default function AgentMessage({ message }: AgentMessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`flex items-center justify-center w-8 h-8 rounded-full shrink-0 ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-[#eef4ff] text-blue-600'
        }`}
      >
        {isUser ? <User size={15} /> : <Bot size={15} />}
      </div>

      <div className="flex flex-col max-w-[80%] min-w-0">
        <div
          className={`px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
            isUser
              ? 'bg-blue-600 text-white rounded-2xl rounded-br-md'
              : 'bg-[#f4f8ff] text-gray-700 rounded-2xl rounded-bl-md border border-[#d7e3f4]'
          }`}
        >
          {渲染消息内容(message.content)}
        </div>

        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <ToolCallStatus toolCalls={message.toolCalls} />
        )}
      </div>
    </div>
  );
}
