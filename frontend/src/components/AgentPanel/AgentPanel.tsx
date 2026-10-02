import CanvasStageApproval from './CanvasStageApproval';
import { canvasPermissionKey, parseCanvasPermissionMode, restoreCanvasActionState, looksLikeConfirmationRequest } from './canvasAgentMode';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, ChevronLeft, ChevronRight, MessageSquarePlus, Trash2 } from 'lucide-react';
import {
  agentChatStream,
  getCanvasAgentActions,
  getVideoCanvasRun,
  type CanvasAgentApproval,
  type CanvasAgentPendingTask,
  type CanvasAgentRequestOptions,
  type CanvasPermissionMode,
  createAgentConversation,
  agentConfirmChanges,
  deleteAgentConversation,
  getAgentPendingChanges,
  getAgentConversation,
  listAgentConversations,
  uploadAgentAttachments,
  type AgentConversationSummary,
  type AgentWorkflowType,
  type VideoCanvasGraph,
} from '../../api';
import AgentMessage from './AgentMessage';
import { renderAgentText } from './agentText';
import AgentInput from './AgentInput';
import QuickActions from './QuickActions';
import CanvasReplyConfirm from './CanvasReplyConfirm';
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
  canvasBlocked?: boolean;
  /** 实时取当前浏览器画布图（含未保存修改）；每次发送时调用，随消息上送后端作读取上下文 */
  getCanvasGraph?: () => VideoCanvasGraph | null;
  onLocalCanvasGraph?: (graph: VideoCanvasGraph, clientRevision?: number) => void;
  getCanvasClientRevision?: () => number;
  /** 取用户当前在画布上选中的节点 ID；随消息上送，助手据此定位“这个节点” */
  getCanvasSelectedNodeIds?: () => string[];
  /** Agent 流式执行状态变化；画布据此在运行期间增量同步节点（不刷新页面、不重置视口） */
  onStreamingChange?: (streaming: boolean) => void;
  /** 外部注入的指令（如空画布模板、流水线"继续"）；id 变化时触发，直接发送 */
  externalPrompt?: { id: number; text: string; mode?: CanvasPermissionMode } | null;
  /** 每次发给助手之前调用（含点击阶段卡片的"同意"）；返回 false 则取消本次发送。画布用它先保存未保存的修改。 */
  onBeforeSend?: () => Promise<boolean>;
}

/** 合并画布 Agent 请求选项：被取代提案的修订 ID 只随当前这一次请求携带，取用后立即清空引用，避免附带到后续消息触发 revise 409。 */
export function buildCanvasAgentEffectiveOptions(
  ref: { current: number | undefined },
  requestOptions?: CanvasAgentRequestOptions,
): CanvasAgentRequestOptions {
  const supersededApprovalId = ref.current;
  ref.current = undefined;
  return {
    ...(supersededApprovalId ? { canvas_revision_approval_id: supersededApprovalId } : {}),
    ...requestOptions,
  };
}

/** 自动模式下系统替用户回答“继续”的固定话术（用它区分系统续跑与用户真实输入）。 */
const AUTO_MODE_CONTINUE_PROMPT = '自动模式已授权，无需确认。请直接执行下一步：把剧本提交为画布节点并继续编排，不要再征求意见。';

/** 组装 video_canvas 工作流的 Agent 流式请求选项；画布写入模式默认 server（由后端落库并广播 canvas_updated）。 */
export function buildCanvasChatOptions(
  permissionMode: CanvasPermissionMode,
  effectiveOptions: CanvasAgentRequestOptions,
  graph: VideoCanvasGraph | undefined,
  clientRevision: number,
  selectedNodeIds?: string[],
): CanvasAgentRequestOptions {
  return {
    canvas_permission_mode: permissionMode,
    ...effectiveOptions,
    canvas_graph: graph,
    canvas_graph_write_mode: 'server',
    canvas_client_revision: clientRevision,
    ...(selectedNodeIds && selectedNodeIds.length ? { canvas_selected_node_ids: selectedNodeIds.slice(0, 20) } : {}),
  };
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
  canvasBlocked = false,
  getCanvasGraph,
  onLocalCanvasGraph,
  getCanvasClientRevision,
  getCanvasSelectedNodeIds,
  onStreamingChange,
  externalPrompt,
  onBeforeSend,
}: AgentPanelProps) {
  const beforeSendRef = useRef(onBeforeSend);
  useEffect(() => { beforeSendRef.current = onBeforeSend; }, [onBeforeSend]);
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<File[]>([]);
  const [messages, setMessages] = useState<AgentMessageData[]>([]);
  const [streaming, setStreaming] = useState(false);
  useEffect(() => { onStreamingChange?.(streaming); }, [streaming, onStreamingChange]);
  useEffect(() => () => onStreamingChange?.(false), [onStreamingChange]);
  const [streamContent, setStreamContent] = useState('');
  const [streamStatus, setStreamStatus] = useState('');
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
  const [modeOverrides, setModeOverrides] = useState<Record<string, CanvasPermissionMode>>({});
  const turnEpochRef = useRef(0);
  const conversationRef = useRef(activeConversationId);
  useEffect(() => {
    conversationRef.current = activeConversationId;
  }, [activeConversationId]);
  const [approval, setApproval] = useState<CanvasAgentApproval | null>(null);
  const [pendingTask, setPendingTask] = useState<CanvasAgentPendingTask | null>(null);
  const [waitError, setWaitError] = useState('');
  const [autoContinue, setAutoContinue] = useState(true);
  const sendLockRef = useRef(false);
  const resumedRunsRef = useRef(new Set<string>());
  const supersededApprovalRef = useRef<number | undefined>(undefined);
  const sendRef = useRef<(message: string, options?: CanvasAgentRequestOptions) => Promise<void>>(async () => {});
  /** 本会话刚结束的那条助手消息 ID：自动模式只对“刚刚生成”的回复自动续跑，打开历史对话不会触发。 */
  const justFinishedMessageRef = useRef<string | null>(null);
  const autoAnsweredRef = useRef<string | null>(null);
  const autoAnswerCountRef = useRef(0);
  const canvasMode = workflowType === 'video_canvas';
  const permissionMode = useMemo<CanvasPermissionMode>(() => {
    if (!workflowId || !canvasMode) return 'ask';
    const specificKey = canvasPermissionKey(workflowId, activeConversationId);
    const defaultKey = canvasPermissionKey(workflowId);
    if (modeOverrides[specificKey]) return modeOverrides[specificKey];
    try {
      const saved = localStorage.getItem(specificKey);
      return saved ? parseCanvasPermissionMode(saved) : modeOverrides[defaultKey] || parseCanvasPermissionMode(localStorage.getItem(defaultKey));
    } catch { return modeOverrides[defaultKey] || 'ask'; }
  }, [workflowId, activeConversationId, canvasMode, modeOverrides]);
  const changePermissionMode = (mode: CanvasPermissionMode) => {
    if (!workflowId || (pendingTask && !['failed', 'cancelled'].includes(pendingTask.status))) return;
    if (approval && mode !== permissionMode) {
      // 模式切换只丢弃本地提案：清空可能残留的修订引用，旧提案 ID 不排队进后续消息，避免孤儿 revision 触发 revise 409。
      supersededApprovalRef.current = undefined;
      setApproval(null);
      setWaitError('已切换模式，旧提案不会执行。发送你的要求后，助手会按新模式重新提出方案。');
    }
    try { localStorage.setItem(canvasPermissionKey(workflowId, activeConversationId), mode); localStorage.setItem(canvasPermissionKey(workflowId), mode); } catch { /* 浏览器禁用存储时继续使用当前会话。 */ }
    setModeOverrides(current => ({ ...current, [canvasPermissionKey(workflowId, activeConversationId)]: mode, [canvasPermissionKey(workflowId)]: mode }));
  };

  useEffect(() => {
    setApproval(null);
    setPendingTask(null);
    setWaitError('');
    setAutoContinue(true);
    supersededApprovalRef.current = undefined;
    if (!canvasMode || !activeConversationId || !workflowId) return;
    let active = true;
    void getCanvasAgentActions(storyId, activeConversationId).then(result => {
      if (!active || sendLockRef.current) return;
      const restored = restoreCanvasActionState(result.actions, workflowId, result.pending_task);
      setApproval(restored.approval);
      setPendingTask(restored.pendingTask);
      if (restored.mode) {
        const key = canvasPermissionKey(workflowId, activeConversationId);
        setModeOverrides(current => ({ ...current, [key]: restored.mode! }));
        try { localStorage.setItem(key, restored.mode); } catch { /* 本地存储不可用时保留会话状态。 */ }
      }
    }).catch(error => { if (active) setWaitError(error.message || '读取制作进度失败'); });
    return () => { active = false; };
  }, [storyId, activeConversationId, workflowId, canvasMode]);


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
      const epoch = ++turnEpochRef.current;
      sendLockRef.current = false;
      setLoadingMessages(true);
      setSidebarError('');
      try {
        const [detail, pending] = await Promise.all([
          getAgentConversation(storyId, conversationId),
          getAgentPendingChanges(storyId, conversationId),
        ]);
        if (turnEpochRef.current !== epoch) return;
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
      turnEpochRef.current += 1;
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
      sendLockRef.current = false;
      setAutoContinue(false);
      setPendingTask(null);
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
        if (sendLockRef.current || (conversationRef.current !== conversationId && conversationRef.current !== null)) return;
        setConversations(items);
        if (conversationRef.current === conversationId || conversationRef.current === null) {
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
    async (overrideContent?: string, requestOptions?: CanvasAgentRequestOptions) => {
      const typedContent = (overrideContent ?? input).trim();
      if ((!typedContent && attachments.length === 0) || streaming || sendLockRef.current || !storyId || (canvasMode && canvasBlocked)) return;
      sendLockRef.current = true;
      const epoch = ++turnEpochRef.current;
      const isCurrent = () => turnEpochRef.current === epoch;
      // 助手在服务端读写画布：本地未保存的节点它看不到，先保存再发送，避免服务端与浏览器各持一份不同的图。
      if (canvasMode && beforeSendRef.current) {
        const ready = await beforeSendRef.current().catch(() => false);
        if (!isCurrent()) return;
        if (!ready) { sendLockRef.current = false; return; }
      }
      setAutoContinue(true);
      setWaitError('');
      const content = typedContent || '请分析我上传的附件，并给出可直接用于创作的结构化建议。';
      let attachmentIds: string[] = [];
      if (attachments.length) {
        try {
          attachmentIds = (await uploadAgentAttachments(storyId, attachments)).map((item) => item.id);
          if (!isCurrent()) return;
        } catch (error: any) {
          if (!isCurrent()) return;
          setSidebarError(error?.message || '附件上传失败');
          sendLockRef.current = false;
          return;
        }
      }

      let conversationId = activeConversationId;
      if (!conversationId) {
        try {
          const created = await createAgentConversation(storyId, chapterId ? { chapter_id: chapterId } : undefined);
          if (!isCurrent()) return;
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
          if (!isCurrent()) return;
          setSidebarError(error?.message || '新建对话失败');
          sendLockRef.current = false;
          return;
        }
      }

      if (content !== AUTO_MODE_CONTINUE_PROMPT) autoAnswerCountRef.current = 0;
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
      setStreamStatus('');
      setSidebarError('');
      if (canvasMode) { setApproval(null); setPendingTask(null); }

      let accumulated = '';
      const toolCallMap = new Map<string, ToolCallInfo>();

      // 修订提案只允许被当前这一次请求消费；附件上传或建会话失败时保留它，便于用户重试。
      const effectiveOptions = buildCanvasAgentEffectiveOptions(supersededApprovalRef, requestOptions);
      abortRef.current = agentChatStream(storyId, conversationId, content, chapterId, workflowType, workflowId, shotId, undefined, attachmentIds, {
        onStatus: (message: string) => { if (isCurrent()) setStreamStatus(message); },
        onToken: (token: string) => {
          if (!isCurrent()) return;
          setStreamStatus('');
          accumulated += token;
          setStreamContent(accumulated);
        },
        onToolCall: (toolCall: ToolCallInfo) => {
          if (!isCurrent()) return;
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
          if (!isCurrent()) return;
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
        onStagePending: action => { if (isCurrent() && (!action.canvas_id || action.canvas_id === workflowId)) setApproval(action); },
        onWaiting: task => { if (!isCurrent() || task.canvas_id !== workflowId) return; setPendingTask({ ...task, permission_mode: effectiveOptions.canvas_permission_mode || permissionMode }); onContentUpdated?.(); },
        onCanvasUpdated: payload => {
          if (!isCurrent()) return;
          if (payload?.write_mode === 'local' && payload.graph) onLocalCanvasGraph?.(payload.graph, payload.client_revision);
          else onContentUpdated?.();
        },
        onDone: (content: string, changes?: PendingChangeItem[], runId?: string) => {
          if (!isCurrent()) return;
          abortRef.current = null;
          sendLockRef.current = false;
          if (canvasMode) onContentUpdated?.();
          justFinishedMessageRef.current = emptyAssistantMsg.id;
          if (canvasMode && workflowId) {
            // 不只依赖流里的 stage_pending 事件：事件丢失 / 断流时，确认卡片也要以服务端待办为准恢复，避免“卡片丢失”。
            void getCanvasAgentActions(storyId, conversationId).then(result => {
              if (!isCurrent()) return;
              const restored = restoreCanvasActionState(result.actions, workflowId, result.pending_task);
              setApproval(previous => restored.approval ?? previous);
              setPendingTask(previous => restored.pendingTask ?? previous);
            }).catch(() => undefined);
          }
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
          if (!isCurrent()) return;
          abortRef.current = null;
          sendLockRef.current = false;
          setWaitError(message);
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
          if (canvasMode && workflowId) {
            // 失败后以服务端为准恢复待确认提案：仍有效的卡片重新出现，已作废的（画布被改动）不再残留。
            void getCanvasAgentActions(storyId, conversationId).then(result => {
              if (!isCurrent()) return;
              const restored = restoreCanvasActionState(result.actions, workflowId, result.pending_task);
              setApproval(restored.approval);
              setPendingTask(restored.pendingTask);
            }).catch(() => undefined);
          }
          if (code === 'agent_multimodal_unsupported') {
            toast.error(message, 9000);
          }
          void syncAfterStream(conversationId);
        },
      }, canvasMode ? buildCanvasChatOptions(permissionMode, effectiveOptions, getCanvasGraph?.() ?? undefined, getCanvasClientRevision?.() ?? 0, getCanvasSelectedNodeIds?.()) : undefined);
    },
    [canvasBlocked, canvasMode, getCanvasGraph, getCanvasSelectedNodeIds, getCanvasClientRevision, permissionMode, activeConversationId, attachments, chapterId, generateId, input, onContentUpdated, storyId, streaming, syncAfterStream, workflowType, workflowId, shotId],
  );

  useEffect(() => { sendRef.current = handleSend; }, [handleSend]);
  useEffect(() => {
    // 自动模式不应该向用户要确认：模型仍然在文字里征求意见时，系统替用户回答“继续”（同一轮最多两次，防止空转）。
    if (!canvasMode || permissionMode !== 'auto' || streaming || loadingMessages || approval || pendingTask || canvasBlocked) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'assistant' || last.id !== justFinishedMessageRef.current || autoAnsweredRef.current === last.id) return;
    if (!looksLikeConfirmationRequest(last.content) || autoAnswerCountRef.current >= 2) return;
    autoAnsweredRef.current = last.id;
    autoAnswerCountRef.current += 1;
    void sendRef.current(AUTO_MODE_CONTINUE_PROMPT);
  }, [canvasMode, permissionMode, streaming, loadingMessages, approval, pendingTask, canvasBlocked, messages]);
  const lastExternalPromptRef = useRef(0);
  useEffect(() => {
    if (!externalPrompt || externalPrompt.id === lastExternalPromptRef.current || streaming) return;
    lastExternalPromptRef.current = externalPrompt.id;
    const mode = externalPrompt.mode;
    if (mode && canvasMode && workflowId) {
      // 开场引导里选的模式：写入本地偏好并立刻生效，本条消息也按它发送（不依赖状态刷新）
      try { localStorage.setItem(canvasPermissionKey(workflowId, activeConversationId), mode); localStorage.setItem(canvasPermissionKey(workflowId), mode); } catch { /* 存储不可用时只对本会话生效 */ }
      setModeOverrides(current => ({ ...current, [canvasPermissionKey(workflowId, activeConversationId)]: mode, [canvasPermissionKey(workflowId)]: mode }));
    }
    void sendRef.current(externalPrompt.text, mode ? { canvas_permission_mode: mode } : undefined);
  }, [externalPrompt, streaming]);
  useEffect(() => {
    if (!canvasMode || !pendingTask || !autoContinue || ['succeeded', 'failed', 'cancelled'].includes(pendingTask.status)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 30 * 60 * 1000;
    let failures = 0;
    const poll = async () => {
      try {
        const result = await getVideoCanvasRun(pendingTask.canvas_id, pendingTask.run_id);
        if (!active) return;
        failures = 0;
        if (['succeeded', 'failed', 'cancelled'].includes(result.run.status)) {
          setPendingTask({ ...pendingTask, status: result.run.status });
          onContentUpdated?.();
          return;
        }
      } catch (error) {
        failures += 1;
        if (!active) return;
        if (failures >= 3) { setWaitError(error instanceof Error ? error.message : '读取生成进度失败'); setAutoContinue(false); return; }
      }
      if (Date.now() >= deadline) { setWaitError('本次等待已暂停，任务仍可在后台继续。稍后可恢复查看进度。'); setAutoContinue(false); return; }
      timer = setTimeout(() => void poll(), 3000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [canvasMode, pendingTask?.canvas_id, pendingTask?.run_id, pendingTask?.status, autoContinue]);

  useEffect(() => {
    if (!pendingTask || pendingTask.status !== 'succeeded' || !autoContinue || streaming || canvasBlocked || sendLockRef.current) return;
    const key = `${pendingTask.canvas_id}:${pendingTask.run_id}`;
    if (resumedRunsRef.current.has(key)) return;
    if (resumedRunsRef.current.size >= 24) { setAutoContinue(false); setWaitError('已连续推进多个制作阶段，请检查当前结果后继续。'); return; }
    resumedRunsRef.current.add(key);
    void sendRef.current('生成任务已完成，请观察实际结果并继续后续制作阶段。', { canvas_resume_run_id: pendingTask.run_id, ...(pendingTask.permission_mode ? { canvas_permission_mode: pendingTask.permission_mode } : {}) });
  }, [pendingTask, autoContinue, streaming, canvasBlocked]);

  const handleAbort = useCallback(() => {
    turnEpochRef.current += 1;
    sendLockRef.current = false;
    setAutoContinue(false);
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

  // 画布模式不再显示底部“保留/撤回”横幅：写入前已有阶段/改动确认卡片，写入后的回退走画布“版本历史”。
  // 保留横幅会与确认卡重复，且后台编排仍在写画布时点“撤回”会把图回滚到旧版本，与流程互相覆盖。
  const autoConfirmChanges = canvasMode;
  useEffect(() => {
    if (!autoConfirmChanges || streaming || pendingChanges.length === 0 || !activeConversationId) return;
    let active = true;
    void agentConfirmChanges(storyId, activeConversationId, pendingRunId).then(() => {
      if (!active) return;
      setPendingChanges([]);
      setPendingRunId(null);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [activeConversationId, autoConfirmChanges, pendingChanges.length, pendingRunId, storyId, streaming]);

  const handleRollbackChanges = useCallback(() => {
    notifyMangaAssetAnalysisChanges(pendingChanges);
    setPendingChanges([]);
    setPendingRunId(null);
    onContentUpdated?.();
  }, [onContentUpdated, pendingChanges]);

  return (
    <div className="relative flex h-full min-h-0 w-full min-w-0 max-w-full overflow-hidden bg-white/90 backdrop-blur-xl">
      {/* 画布里面板只有约 400px：窄栏占位 52px，展开时作为抽屉浮在聊天区上，聊天区宽度不变。 */}
      <div className={canvasMode ? 'relative z-30 w-[52px] shrink-0' : 'contents'}>
      {canvasMode && !sidebarCollapsed && <button type="button" aria-label="收起历史对话" className="fixed inset-0 z-20 cursor-default" onClick={() => setSidebarCollapsed(true)} />}
      <aside
        className={`flex shrink-0 flex-col border-r border-[#d7e3f4] transition-all duration-200 ${
          sidebarCollapsed ? 'w-[52px] bg-[rgba(244,248,255,0.75)]' : canvasMode ? 'absolute left-0 top-0 z-30 h-full w-[min(240px,70vw)] bg-[#f4f8ff] shadow-2xl' : 'w-[156px] bg-[rgba(244,248,255,0.75)]'
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
                        onClick={() => { void handleSelectConversation(item.id); if (canvasMode) setSidebarCollapsed(true); }}
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
      </div>

      <div className="flex min-h-0 w-0 min-w-0 flex-1 flex-col overflow-hidden">
        {(!canvasMode || Boolean(contextLabel)) && (
          <div className="flex items-center gap-2 border-b border-[#d7e3f4] px-5 py-3 shrink-0">
            {!canvasMode && (
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-100">
                <Bot size={16} className="text-blue-600" />
              </div>
            )}
            {!canvasMode && <span className="text-sm font-semibold text-gray-800">AI 助手</span>}
            {contextLabel ? <span className="truncate text-xs text-gray-500">{contextLabel}</span> : null}
          </div>
        )}

        <div ref={scrollContainerRef} style={{ scrollbarGutter: 'stable' }} className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-3 py-4 space-y-4 sm:px-5">
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
                        <span className="text-sm text-gray-500">{streamStatus || 'AI 思考中...'}</span>
                      </div>
                    )}
                  </div>
                </div>
              ) : null}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {canvasMode && approval && !streaming && <CanvasStageApproval key={approval.id} approval={approval} disabled={canvasBlocked || loadingMessages} onApprove={() => void handleSend('已在阶段卡片确认，执行此阶段。', { canvas_approval_id: approval.id, ...(approval.permission_mode ? { canvas_permission_mode: approval.permission_mode } : {}) })} onRevise={suggestion => void handleSend(`请修改这个阶段的提案：${suggestion}`, { canvas_revision_approval_id: approval.id })} />}
        {canvasMode && permissionMode !== 'auto' && !approval && !pendingTask && !streaming && !loadingMessages && (() => { const last = messages[messages.length - 1]; return last?.role === 'assistant' && looksLikeConfirmationRequest(last.content); })() && <CanvasReplyConfirm disabled={canvasBlocked} onConfirm={() => void handleSend('确认，请继续下一步。')} onRevise={suggestion => void handleSend(`请按以下意见修改后重新给我确认：${suggestion}`)} />}
        {canvasMode && pendingTask && !streaming && <div className="mx-3 mb-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600" role="status">
          <p>{pendingTask.status === 'succeeded' ? '生成完成，准备观察结果并继续。' : pendingTask.status === 'failed' ? '生成任务失败，请检查结果后决定恢复原任务或调整制作方案。' : pendingTask.status === 'cancelled' ? '生成任务已取消。' : '后台正在生成，完成后助手会观察结果并继续。'}</p>
          {waitError && <p className="mt-2 text-amber-700">{waitError}</p>}
          {!['failed', 'cancelled'].includes(pendingTask.status) && <button type="button" onClick={() => { if (!autoContinue && resumedRunsRef.current.size >= 24) resumedRunsRef.current.clear(); setAutoContinue(value => !value); setWaitError(''); }} className="mt-2 text-blue-600">{autoContinue ? '暂停自动续接' : '恢复查看并继续'}</button>}
        </div>}
        {canvasMode && waitError && !pendingTask && <p className="mx-3 mb-2 text-xs text-amber-700">{waitError}</p>}
        {pendingChanges.length > 0 && !streaming && !autoConfirmChanges ? (
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
          <AgentInput
            value={input}
            onChange={setInput}
            onSend={() => void handleSend()}
            streaming={streaming}
            onStop={handleAbort}
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            disabled={loadingMessages || (canvasMode && canvasBlocked)}
            permissionMode={canvasMode ? permissionMode : undefined}
            permissionModeDisabled={Boolean(pendingTask && !['failed', 'cancelled'].includes(pendingTask.status))}
            onPermissionModeChange={changePermissionMode}
            placeholder="输入你的问题，AI 助手会保留在当前历史会话里"
          />
        </div>
      </div>
    </div>
  );
}
