import { defineStore } from 'pinia'
import { ref } from 'vue'
import { agentApi } from '@/api'
import { useSSE } from '@/composables/useSSE'
import { getToken } from '@/utils/storage'
import {
  getToolResultStatus,
  sanitizeAgentMessages,
  sanitizeToolSummary
} from '@/utils/agent-tool-display'
import type { AgentConversationSummary, AgentMessage, ToolCallInfo, PendingChange } from '@/api/types'

export const useAgentStore = defineStore('agent', () => {
  const conversations = ref<AgentConversationSummary[]>([])
  const activeConversationId = ref<number | null>(null)
  const messages = ref<AgentMessage[]>([])
  const streaming = ref(false)
  const streamingContent = ref('')
  const streamingToolCalls = ref<ToolCallInfo[]>([])
  const pendingChanges = ref<PendingChange[]>([])
  const loading = ref(false)

  let sseHandle: ReturnType<typeof useSSE> | null = null
  let _sseResolve: (() => void) | null = null

  async function loadConversations(storyId: number) {
    loading.value = true
    try {
      conversations.value = await agentApi.getConversations(storyId)
    } finally {
      loading.value = false
    }
  }

  async function createConversation(storyId: number, title?: string, chapterId?: number) {
    const conv = await agentApi.createConversation(storyId, title, chapterId)
    conversations.value.unshift(conv as unknown as AgentConversationSummary)
    activeConversationId.value = conv.id
    messages.value = []
    return conv
  }

  async function loadConversation(storyId: number, conversationId: number) {
    loading.value = true
    try {
      const conv = await agentApi.getConversation(storyId, conversationId)
      activeConversationId.value = conv.id
      messages.value = sanitizeAgentMessages(conv.messages)
    } finally {
      loading.value = false
    }
  }

  async function deleteConversation(storyId: number, conversationId: number) {
    await agentApi.deleteConversation(storyId, conversationId)
    conversations.value = conversations.value.filter(c => c.id !== conversationId)
    if (activeConversationId.value === conversationId) {
      activeConversationId.value = null
      messages.value = []
    }
  }

  async function sendMessage(storyId: number, content: string, chapterId?: number) {
    // 重置前一次 Promise 引用
    _sseResolve = null

    // 如果没有活跃对话，自动创建一个
    if (!activeConversationId.value) {
      const conv = await createConversation(storyId, undefined, chapterId)
      activeConversationId.value = conv.id
    }

    const userMsg: AgentMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content
    }
    messages.value.push(userMsg)
    streamingContent.value = ''
    streamingToolCalls.value = []
    streaming.value = true

    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`

    return new Promise<void>((resolve, reject) => {
      _sseResolve = resolve
      const sse = useSSE()
      sseHandle = sse

      sse.start({
        url: agentApi.chatUrl(storyId),
        headers,
        body: {
          conversation_id: activeConversationId.value,
          message: content,
          chapter_id: chapterId,
          mode: 'execute'
        },
        onEvent: (event) => {
          switch (event.type) {
            case 'token':
              streamingContent.value += event.data.content
              break
            case 'tool_call':
              streamingToolCalls.value.push({
                id: String(event.data.id || `${event.data.name || 'tool'}-${streamingToolCalls.value.length}`),
                name: String(event.data.name || 'tool'),
                args: event.data.arguments || event.data.args || {},
                status: 'running'
              })
              break
            case 'tool_result': {
              const tool = [...streamingToolCalls.value].reverse().find(item =>
                item.status === 'running' && (
                  (event.data.id && item.id === String(event.data.id))
                  || item.name === String(event.data.name || 'tool')
                )
              )
              if (tool) {
                tool.summary = sanitizeToolSummary(
                  tool.name,
                  event.data.summary ?? event.data.result,
                  event.data.error
                )
                tool.status = getToolResultStatus(event.data.result, event.data.error)
              }
              break
            }
            case 'done': {
              const assistantMsg: AgentMessage = {
                id: `assistant-${Date.now()}`,
                role: 'assistant',
                content: event.data.content || streamingContent.value,
                toolCalls: streamingToolCalls.value.length > 0 ? [...streamingToolCalls.value] : undefined
              }
              messages.value.push(assistantMsg)
              streamingContent.value = ''
              streamingToolCalls.value = []
              streaming.value = false
              if (event.data.pending_changes) {
                pendingChanges.value = event.data.pending_changes
              }
              _sseResolve = null
              resolve()
              break
            }
            case 'error':
              streaming.value = false
              streamingContent.value = ''
              streamingToolCalls.value = []
              _sseResolve = null
              reject(new Error(event.data?.error || '请求失败'))
              break
          }
        },
        onError: (err) => {
          streaming.value = false
          streamingContent.value = ''
          streamingToolCalls.value = []
          _sseResolve = null
          reject(err)
        },
        onComplete: () => {
          streaming.value = false
          _sseResolve = null
          resolve()
        }
      })
    })
  }

  function stopStreaming() {
    sseHandle?.stop()
    streaming.value = false
    if (streamingContent.value) {
      const assistantMsg: AgentMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: streamingContent.value,
        toolCalls: streamingToolCalls.value.length > 0 ? [...streamingToolCalls.value] : undefined
      }
      messages.value.push(assistantMsg)
      streamingContent.value = ''
    }
    streamingToolCalls.value = []
    _sseResolve?.()
    _sseResolve = null
  }

  async function confirmChanges(storyId: number) {
    const result = await agentApi.confirmChanges(storyId, activeConversationId.value ?? undefined)
    pendingChanges.value = []
    return result
  }

  async function rollbackChanges(storyId: number) {
    const result = await agentApi.rollbackChanges(storyId, activeConversationId.value ?? undefined)
    pendingChanges.value = []
    return result
  }

  async function loadPendingChanges(storyId: number) {
    const result = await agentApi.getPendingChanges(storyId, activeConversationId.value ?? undefined)
    pendingChanges.value = result.changes || []
  }

  return {
    conversations,
    activeConversationId,
    messages,
    streaming,
    streamingContent,
    streamingToolCalls,
    pendingChanges,
    loading,
    loadConversations,
    createConversation,
    loadConversation,
    deleteConversation,
    sendMessage,
    stopStreaming,
    confirmChanges,
    rollbackChanges,
    loadPendingChanges
  }
})
