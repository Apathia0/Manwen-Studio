import { Bot, User } from 'lucide-react';
import type { AgentMessageData } from './AgentPanel';
import { renderAgentText } from './agentText';
import ToolCallStatus from './ToolCallStatus';

interface AgentMessageProps { message: AgentMessageData }

export default function AgentMessage({ message }: AgentMessageProps) {
  const isUser = message.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${isUser ? 'bg-blue-600 text-white' : 'bg-[#eef4ff] text-blue-600'}`}>
        {isUser ? <User size={15} /> : <Bot size={15} />}
      </div>
      <div className="flex min-w-0 max-w-[min(80%,100%)] flex-col">
        <div className={`max-h-[50vh] overflow-y-auto overflow-x-hidden [overflow-wrap:anywhere] px-3.5 py-2.5 text-sm leading-relaxed ${isUser ? 'rounded-2xl rounded-br-md bg-blue-600 text-white' : 'rounded-2xl rounded-bl-md border border-[#d7e3f4] bg-[#f4f8ff] text-gray-700'}`}>
          {isUser ? <div className="whitespace-pre-wrap">{message.content}</div> : renderAgentText(message.content)}
        </div>
        {!isUser && message.toolCalls?.length ? <ToolCallStatus toolCalls={message.toolCalls} /> : null}
      </div>
    </div>
  );
}
