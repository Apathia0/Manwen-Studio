import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, ChevronLeft, ChevronRight, MessageSquarePlus, Square, Trash2 } from 'lucide-react';
import {
  agentChatStream,
  createAgentConversation,
  deleteAgentConversation,
  getAgentPendingChanges,
  getAgentConversation,
  listAgentConversations,
  uploadAgentAttachments,
  type AgentConversationSummary,
  type AgentWorkflowType,
} from '../../api';
import AgentMessage from './AgentMessage';
import { renderAgentText } from './agentText';
import AgentInput from './AgentInput';
import QuickActions from './QuickActions';
import ChangesBanner from './ChangesBanner';
import type { PendingChangeItem } from './ChangesBanner';
import { toast } from '../../lib/toast';
import { notifyMangaAssetAnalysisChanges } from '../../mangaAssetAnalysisSync';

export interface ToolCallInfo {
  id: string;
  name: string;
  args: Record<string, any>;
  status: 'running' | 'success' | 'error';
  summary?: string;
}

export interface AgentMessageData {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCallInfo[];
}

export interface AgentPanelProps {
  storyId: number;
  chapterId?: number;
  chapterNumber?: number;
  storyTitle?: string;
  chapterTitle?: string;
  onContentUpdated?: () => void;
  workflowType?: AgentWorkflowType;
  workflowId?: number;
  shotId?: number;
}

function mapConversationMessage(message: {
  id: number;
  role: 'user' | 'assistant';
  content: string;
}): AgentMessageData {
  return {
    id: `persisted_${message.id}`,
    role: message.role,
    content: message.content,
  };
}

function formatRelativeTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return '';
  const diffMinutes = Math.max(0, Math.round((Date.now() - timestamp) / 60000));
  if (diffMinutes < 1) return '刚刚';
  if (diffMinutes < 60) return `${diffMinutes}分钟前`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}小时前`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 7) return `${diffDays}天前`;
  return new Date(value).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
}

function buildConversationSummaryPreview(item: AgentConversationSummary): string {
  return item.last_message_preview || '暂时还没有消息';
}

function WelcomeScreen({
  storyTitle,
  chapterTitle,
  onAction,
  disabled,
  workflowType,
}: {
  storyTitle?: string;
  chapterTitle?: string;
  onAction: (prompt: string) => void;
  disabled: boolean;
  workflowType?: AgentWorkflowType;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-100 to-blue-50 shadow-sm">
        <Bot size={32} className="text-blue-600" />
      </div>
      <h3 className="mb-2 text-lg font-semibold text-gray-800">AI 创作助手</h3>
      <p className="mb-6 max-w-sm text-sm leading-relaxed text-gray-500">
        {storyTitle
          ? `正在创作《${storyTitle}》${chapterTitle ? ` · ${chapterTitle}` : ''}，让 AI 帮你分析、润色和推进创作。`
          : '选择一部小说后，AI 助手会在这里保留历史对话，并持续协助创作。'}
      </p>
      <div className="w-full max-w-md">
        <QuickActions onAction={onAction} disabled={disabled} workflowType={workflowType} />
      </div>
    </div>
  );
}

export default function AgentPanel({
  storyId,
  chapterId,
  chapterNumber,
  storyTitle,
  chapterTitle,
  onContentUpdated,
  workflowType,
  workflowId,
  shotId,
}: AgentPanelProps) {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<File[]>([]);
  const [messages, setMessages] = useState<AgentMessageData[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState('');
  const [pendingChanges, setPendingChanges] = useState<PendingChangeItem[]>([]);
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [deletingConversationId, setDeletingConversationId] = useState<number | null>(null);
  const [sidebarError, setSidebarError] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const userScrolledUp = useRef(false);

  const contextLabel = useMemo(
    () =>
      [
        storyTitle ? `《${storyTitle}》` : '',
        chapterId && chapterTitle ? `第${chapterNumber ?? chapterId}话 · ${chapterTitle}` : '',
      ]
        .filter(Boolean)
        .join(' · '),
    [storyTitle, chapterTitle, chapterId, chapterNumber],
  );

  const generateId = useCallback(() => `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`, []);

  const loadConversation = useCallback(
    async (conversationId: number) => {
      setLoadingMessages(true);
      setSidebarError('');
      try {
        const [detail, pending] = await Promise.all([
          getAgentConversation(storyId, conversationId),
          getAgentPendingChanges(storyId, conversationId),
        ]);
        setActiveConversationId(detail.id);
        setMessages(detail.messages.map(mapConversationMessage));
        setPendingChanges(pending.changes ?? []);
        setPendingRunId(null);
      } catch (error: any) {
        setSidebarError(error?.message || '加载助手对话失败');
      } finally {
        setLoadingMessages(false);
      }
    },
    [storyId],
  );

  const refreshConversationList = useCallback(
    async (preferredConversationId?: number | null, options?: { skipDetail?: boolean }) => {
      setLoadingConversations(true);
      setSidebarError('');
      try {
        const items = await listAgentConversations(storyId);
        setConversations(items);
        const existingActive = preferredConversationId ?? activeConversationId;
        const resolvedId = existingActive && items.some((item) => item.id === existingActive)
          ? existingActive
          : (items[0]?.id ?? null);
        if (resolvedId === null) {
          setActiveConversationId(null);
          setMessages([]);
          setPendingChanges([]);
        } else if (!options?.skipDetail) {
          await loadConversation(resolvedId);
        } else {
          setActiveConversationId(resolvedId);
        }
      } catch (error: any) {
        setSidebarError(error?.message || '获取历史对话失败');
      } finally {
        setLoadingConversations(false);
      }
    },
    [activeConversationId, loadConversation, storyId],
  );

  useEffect(() => {
    void refreshConversationList(null);
  }, [storyId]);

  useEffect(() => {
    if (!userScrolledUp.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: streaming ? 'instant' : 'smooth' });
    }
  }, [messages, streamContent, streaming]);

  useEffect(() => {
    userScrolledUp.current = false;
  }, [messages.length, activeConversationId]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const handleScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      userScrolledUp.current = !atBottom;
    };
    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleNewConversation = useCallback(async () => {
    if (streaming) return;
    setSidebarError('');
    try {
      const created = await createAgentConversation(storyId, chapterId ? { chapter_id: chapterId } : undefined);
      const summary: AgentConversationSummary = {
        id: created.id,
        story_id: created.story_id,
        chapter_id: created.chapter_id ?? null,
        title: created.title,
        last_message_preview: '',
        message_count: 0,
        created_at: created.created_at,
        updated_at: created.updated_at,
      };
      setConversations((prev) => [summary, ...prev.filter((item) => item.id !== created.id)]);
      setActiveConversationId(created.id);
      setMessages([]);
      setPendingChanges([]);
      setInput('');
      setSidebarCollapsed(false);
    } catch (error: any) {
      setSidebarError(error?.message || '新建对话失败');
    }
  }, [chapterId, storyId, streaming]);

  const handleSelectConversation = useCallback(
    async (conversationId: number) => {
      if (conversationId === activeConversationId && !loadingMessages) return;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      setStreaming(false);
      setStreamContent('');
      await loadConversation(conversationId);
    },
    [activeConversationId, loadConversation, loadingMessages],
  );

  const handleDeleteConversation = useCallback(
    async (conversationId: number) => {
      if (streaming || deletingConversationId === conversationId) return;
      setDeletingConversationId(conversationId);
      setSidebarError('');
      try {
        await deleteAgentConversation(storyId, conversationId);
        const remaining = conversations.filter((item) => item.id !== conversationId);
        setConversations(remaining);
        if (activeConversationId === conversationId) {
          const nextConversationId = remaining[0]?.id ?? null;
          setActiveConversationId(nextConversationId);
          setPendingChanges([]);
          if (nextConversationId) {
            await loadConversation(nextConversationId);
          } else {
            setMessages([]);
          }
        }
      } catch (error: any) {
        setSidebarError(error?.message || '删除对话失败');
      } finally {
        setDeletingConversationId(null);
      }
    },
    [activeConversationId, conversations, deletingConversationId, loadConversation, storyId, streaming],
  );

  const syncAfterStream = useCallback(
    async (conversationId: number) => {
      try {
        const [items, detail, pending] = await Promise.all([
          listAgentConversations(storyId),
          getAgentConversation(storyId, conversationId),
          getAgentPendingChanges(storyId, conversationId),
        ]);
        setConversations(items);
        if (activeConversationId === conversationId || activeConversationId === null) {
          setActiveConversationId(detail.id);
          const serverMessages = detail.messages.map(mapConversationMessage);
          setMessages((currentMessages) => {
            const localLast = currentMessages[currentMessages.length - 1];
            const serverIsBehindOptimisticReply = (
              localLast?.role === 'assistant'
              && Boolean(localLast.content)
              && serverMessages.length < currentMessages.length
            );
            return serverIsBehindOptimisticReply ? currentMessages : serverMessages;
          });
          const changes = pending.changes ?? [];
          setPendingChanges(changes);
          // Agent 写入已经提交；待用户确认前也要让已打开的资产工作台读取最新提示词。
          notifyMangaAssetAnalysisChanges(changes);
          setPendingRunId(null);
        }
      } catch {
        // Keep optimistic UI if refresh fails.
      }
    },
    [activeConversationId, storyId],
  );

  const handleSend = useCallback(
    async (overrideContent?: string) => {
      const typedContent = (overrideContent ?? input).trim();
      if ((!typedContent && attachments.length === 0) || streaming || !storyId) return;
      const content = typedContent || '请分析我上传的附件，并给出可直接用于创作的结构化建议。';
      let attachmentIds: string[] = [];
      if (attachments.length) {
        try {
          attachmentIds = (await uploadAgentAttachments(storyId, attachments)).map((item) => item.id);
        } catch (error: any) {
          setSidebarError(error?.message || '附件上传失败');
          return;
        }
      }

      let conversationId = activeConversationId;
      if (!conversationId) {
        try {
          const created = await createAgentConversation(storyId, chapterId ? { chapter_id: chapterId } : undefined);
          conversationId = created.id;
          setActiveConversationId(created.id);
          setConversations((prev) => [
            {
              id: created.id,
              story_id: created.story_id,
              chapter_id: created.chapter_id ?? null,
              title: created.title,
              last_message_preview: '',
              message_count: 0,
              created_at: created.created_at,
              updated_at: created.updated_at,
            },
            ...prev.filter((item) => item.id !== created.id),
          ]);
          setMessages([]);
          setSidebarCollapsed(false);
        } catch (error: any) {
          setSidebarError(error?.message || '新建对话失败');
          return;
        }
      }

      const userMsg: AgentMessageData = {
        id: generateId(),
        role: 'user',
        content,
      };
      const emptyAssistantMsg: AgentMessageData = {
        id: generateId(),
        role: 'assistant',
        content: '',
        toolCalls: [],
      };

      setMessages((prev) => [...prev, userMsg, emptyAssistantMsg]);
      setInput('');
      setAttachments([]);
      setStreaming(true);
      setStreamContent('');
      setSidebarError('');

      let accumulated = '';
      const toolCallMap = new Map<string, ToolCallInfo>();

      abortRef.current = agentChatStream(storyId, conversationId, content, chapterId, workflowType, workflowId, shotId, undefined, attachmentIds, {
        onToken: (token: string) => {
          accumulated += token;
          setStreamContent(accumulated);
        },
        onToolCall: (toolCall: ToolCallInfo) => {
          toolCallMap.set(toolCall.id, toolCall);
          setMessages((prev) => {
            const updated = [...prev];
            const lastIndex = updated.length - 1;
            if (lastIndex >= 0 && updated[lastIndex].role === 'assistant') {
              updated[lastIndex] = {
                ...updated[lastIndex],
                toolCalls: Array.from(toolCallMap.values()),
              };
            }
            return updated;
          });
        },
        onToolResult: (result: ToolCallInfo) => {
          toolCallMap.set(result.id, result);
          setMessages((prev) => {
            const updated = [...prev];
            const lastIndex = updated.length - 1;
            if (lastIndex >= 0 && updated[lastIndex].role === 'assistant') {
              updated[lastIndex] = {
                ...updated[lastIndex],
                toolCalls: Array.from(toolCallMap.values()),
              };
            }
            return updated;
          });
        },
        onDone: (content: string, changes?: PendingChangeItem[], runId?: string) => {
          abortRef.current = null;
          const settledContent = content || accumulated;
          setStreamContent('');
          setStreaming(false);
          if (changes && changes.length > 0) {
            setPendingChanges(changes);
            setPendingRunId(runId || null);
            onContentUpdated?.();
          }
          setMessages((prev) => {
            const updated = [...prev];
            const lastIndex = updated.length - 1;
            if (lastIndex >= 0 && updated[lastIndex].role === 'assistant') {
              updated[lastIndex] = {
                ...updated[lastIndex],
                content: settledContent || updated[lastIndex].content,
                toolCalls: Array.from(toolCallMap.values()),
              };
            }
            return updated;
          });
          void syncAfterStream(conversationId);
        },
        onError: ({ message, code }) => {
          abortRef.current = null;
          const errorContent = `${accumulated}${accumulated ? '\n\n' : ''}错误: ${message}`;
          setMessages((prev) => {
            const updated = [...prev];
            const lastIndex = updated.length - 1;
            if (lastIndex >= 0 && updated[lastIndex].role === 'assistant') {
              updated[lastIndex] = {
                ...updated[lastIndex],
                content: errorContent,
              };
            }
            return updated;
          });
          setStreamContent('');
          setStreaming(false);
          setSidebarError(message);
          if (code === 'agent_multimodal_unsupported') {
            toast.error(message, 9000);
          }
          void syncAfterStream(conversationId);
        },
      });
    },
    [activeConversationId, attachments, chapterId, generateId, input, onContentUpdated, storyId, streaming, syncAfterStream, workflowType, workflowId, shotId],
  );

  const handleAbort = useCallback(() => {
    const currentConversationId = activeConversationId;
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    if (streamContent) {
      setMessages((prev) => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (lastIndex >= 0 && updated[lastIndex].role === 'assistant') {
          updated[lastIndex] = {
            ...updated[lastIndex],
            content: `${streamContent}\n\n[已中止]`,
          };
        }
        return updated;
      });
    }
    setStreamContent('');
    setStreaming(false);
    if (currentConversationId) {
      window.setTimeout(() => {
        void syncAfterStream(currentConversationId);
      }, 300);
    }
  }, [activeConversationId, streamContent, syncAfterStream]);

  const handleConfirmChanges = useCallback(() => {
    notifyMangaAssetAnalysisChanges(pendingChanges);
    setPendingChanges([]);
    setPendingRunId(null);
    onContentUpdated?.();
  }, [onContentUpdated, pendingChanges]);

  const handleRollbackChanges = useCallback(() => {
    notifyMangaAssetAnalysisChanges(pendingChanges);
    setPendingChanges([]);
    setPendingRunId(null);
    onContentUpdated?.();
  }, [onContentUpdated, pendingChanges]);

  return (
    <div className="flex h-full min-h-0 bg-white/90 backdrop-blur-xl">
      <aside
        className={`flex shrink-0 flex-col border-r border-[#d7e3f4] bg-[rgba(244,248,255,0.75)] transition-all duration-200 ${
          sidebarCollapsed ? 'w-[52px]' : 'w-[156px]'
        }`}
      >
        <div className={`border-b border-[#d7e3f4] ${sidebarCollapsed ? 'px-2 py-3' : 'px-3 py-3'}`}>
          <div className={`flex items-center ${sidebarCollapsed ? 'flex-col gap-2' : 'justify-between gap-2'}`}>
            {!sidebarCollapsed ? (
              <button
                onClick={() => void handleNewConversation()}
                disabled={streaming}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
              >
                <MessageSquarePlus size={15} />
                新建对话
              </button>
            ) : (
              <button
                onClick={() => void handleNewConversation()}
                disabled={streaming}
                className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
                title="新建对话"
              >
                <MessageSquarePlus size={15} />
              </button>
            )}
            <button
              onClick={() => setSidebarCollapsed((prev) => !prev)}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[#d7e3f4] bg-white text-[#5b7dbd] transition-colors hover:bg-[#f4f8ff]"
              title={sidebarCollapsed ? '展开历史对话' : '折叠历史对话'}
            >
              {sidebarCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
            </button>
          </div>
          {!sidebarCollapsed && sidebarError ? <p className="mt-2 text-[11px] leading-4 text-red-500">{sidebarError}</p> : null}
        </div>

        {!sidebarCollapsed ? (
          <div className="flex-1 overflow-y-auto px-2 py-2 space-y-2">
            {loadingConversations ? (
              <div className="px-2 py-3 text-xs text-gray-400">加载历史中...</div>
            ) : conversations.length === 0 ? (
              <div className="px-2 py-3 text-xs leading-5 text-gray-400">
                还没有历史对话，点击上方按钮开始一个新会话。
              </div>
            ) : (
              conversations.map((item) => {
                const active = item.id === activeConversationId;
                return (
                  <div
                    key={item.id}
                    className={`w-full rounded-2xl border px-3 py-2 text-left transition-all ${
                      active
                        ? 'border-blue-300 bg-white shadow-[0_8px_20px_rgba(59,130,246,0.10)]'
                        : 'border-transparent bg-white/70 hover:border-[#d7e3f4] hover:bg-white'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <button
                        onClick={() => void handleSelectConversation(item.id)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <div className="line-clamp-2 text-xs font-semibold text-gray-700">{item.title || '新对话'}</div>
                      </button>
                      <button
                        onClick={() => void handleDeleteConversation(item.id)}
                        disabled={streaming || deletingConversationId === item.id}
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-gray-300 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-40"
                        title="删除对话"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                    <div className="mt-1 line-clamp-3 text-[11px] leading-4 text-gray-400">
                      {buildConversationSummaryPreview(item)}
                    </div>
                    <div className="mt-2 text-[10px] text-gray-300">{formatRelativeTime(item.updated_at)}</div>
                  </div>
                );
              })
            )}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-2 py-3">
            <div className="flex flex-col items-center gap-2">
              {conversations.slice(0, 6).map((item) => {
                const active = item.id === activeConversationId;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setSidebarCollapsed(false);
                      void handleSelectConversation(item.id);
                    }}
                    className={`flex h-9 w-9 items-center justify-center rounded-xl border text-xs font-semibold transition-all ${
                      active
                        ? 'border-blue-300 bg-white text-blue-600 shadow-[0_6px_16px_rgba(59,130,246,0.12)]'
                        : 'border-transparent bg-white/75 text-gray-500 hover:border-[#d7e3f4] hover:bg-white'
                    }`}
                    title={item.title || '历史对话'}
                  >
                    {item.title.slice(0, 1) || '聊'}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-[#d7e3f4] px-5 py-3 shrink-0">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-100">
            <Bot size={16} className="text-blue-600" />
          </div>
          <span className="text-sm font-semibold text-gray-800">AI 助手</span>
          {contextLabel ? <span className="truncate text-xs text-gray-500">{contextLabel}</span> : null}

        </div>

        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {loadingMessages ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">正在加载对话...</div>
          ) : messages.length === 0 && !streaming ? (
            <WelcomeScreen
              storyTitle={storyTitle}
              chapterTitle={chapterTitle}
              onAction={(prompt) => void handleSend(prompt)}
              disabled={streaming}
              workflowType={workflowType}
            />
          ) : (
            <>
              {messages.map((msg, index) => {
                if (streaming && msg.role === 'assistant' && !msg.content && index === messages.length - 1) {
                  return null;
                }
                return <AgentMessage key={msg.id} message={msg} />;
              })}
              {streaming ? (
                <div className="flex flex-row gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#eef4ff] text-blue-600">
                    <Bot size={16} />
                  </div>
                  <div className="max-w-[80%] rounded-2xl rounded-bl-md border border-[#d7e3f4] bg-[#f4f8ff] px-4 py-2.5">
                    {streamContent ? (
                      <div className="flex flex-col">
                        <div className="text-sm leading-relaxed text-gray-700">{renderAgentText(streamContent)}</div>
                        <span className="ml-0.5 inline-block h-4 w-1.5 rounded-sm bg-blue-500 animate-pulse" />
                      </div>
                    ) : (
                      <div className="flex items-center gap-3">
                        <svg className="h-5 w-5 animate-spin text-blue-500" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        <span className="text-sm text-gray-500">AI 思考中...</span>
                      </div>
                    )}
                  </div>
                </div>
              ) : null}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {pendingChanges.length > 0 && !streaming ? (
          <ChangesBanner
            changes={pendingChanges}
            storyId={storyId}
            conversationId={activeConversationId}
            runId={pendingRunId}
            onConfirm={handleConfirmChanges}
            onRollback={handleRollbackChanges}
          />
        ) : null}



        <div className="shrink-0 border-t border-[#d7e3f4] px-4 py-3">
          {streaming ? (
            <div className="flex items-center justify-center">
              <button
                onClick={handleAbort}
                className="flex items-center gap-2 rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
              >
                <Square size={14} />
                停止生成
              </button>
            </div>
          ) : (
            <AgentInput
              value={input}
              onChange={setInput}
              onSend={() => void handleSend()}
              attachments={attachments}
              onAttachmentsChange={setAttachments}
              disabled={loadingMessages}
              placeholder="输入你的问题，AI 助手会保留在当前历史会话里"
            />
          )}
        </div>
      </div>
    </div>
  );
}
