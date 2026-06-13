import { ref } from 'vue'
import { useSSE } from './useSSE'
import { getToken } from '@/utils/storage'
import type { AgentMessage, ToolCallInfo, PendingChange } from '@/api/types'

export function useAgentChat(storyId: () => number) {
  const { streaming, start, stop } = useSSE()
  const messages = ref<AgentMessage[]>([])
  const streamingContent = ref('')
  const pendingChanges = ref<PendingChange[]>([])
  const activeConversationId = ref<number | null>(null)

  function sendMessage(content: string, chapterId?: number, conversationId?: number) {
    activeConversationId.value = conversationId ?? activeConversationId.value
    messages.value.push({ id: `user-${Date.now()}`, role: 'user', content })
    streamingContent.value = ''

    const body: any = { content }
    if (activeConversationId.value) {
      body.conversation_id = activeConversationId.value
    }
    if (chapterId) {
      body.chapter_id = chapterId
    }
    body.mode = 'execute'

    start({
      url: `/api/stories/${storyId()}/agent/chat`,
      headers: {
        'Authorization': `Bearer ${getToken()}`
      },
      body,
      onEvent: (event) => {
        switch (event.type) {
          case 'token':
            streamingContent.value += event.data.content
            break
          case 'tool_call':
            handleToolCall(event.data)
            break
          case 'tool_result':
            handleToolResult(event.data)
            break
          case 'done':
            messages.value.push({
              id: `assistant-${Date.now()}`,
              role: 'assistant',
              content: event.data.content
            })
            streamingContent.value = ''
            break
          case 'error':
            uni.showToast({ title: event.data.error, icon: 'none' })
            break
        }
      }
    })
  }

  function handleToolCall(data: { id: string; name: string; arguments: Record<string, any> }) {
    const lastAssistant = messages.value[messages.value.length - 1]
    if (lastAssistant && lastAssistant.role === 'assistant') {
      if (!lastAssistant.toolCalls) {
        lastAssistant.toolCalls = []
      }
      lastAssistant.toolCalls.push({
        id: data.id,
        name: data.name,
        args: data.arguments,
        status: 'running'
      })
    }
  }

  function handleToolResult(data: { id: string; name: string; result: string }) {
    const lastAssistant = messages.value[messages.value.length - 1]
    if (lastAssistant && lastAssistant.role === 'assistant' && lastAssistant.toolCalls) {
      const tool = lastAssistant.toolCalls.find(t => t.id === data.id)
      if (tool) {
        tool.status = 'success'
        tool.summary = data.result
      }
    }
  }

  async function loadPendingChanges() {
    try {
      const { agentApi } = await import('@/api')
      const result = await agentApi.getPendingChanges(storyId(), activeConversationId.value ?? undefined)
      pendingChanges.value = result.changes || []
    } catch (e) {
      console.error('加载待确认变更失败:', e)
    }
  }

  async function confirmChanges() {
    try {
      const { agentApi } = await import('@/api')
      await agentApi.confirmChanges(storyId(), activeConversationId.value ?? undefined)
      pendingChanges.value = []
      uni.showToast({ title: '已确认变更', icon: 'success' })
    } catch (e) {
      uni.showToast({ title: '确认失败', icon: 'none' })
    }
  }

  async function rollbackChanges() {
    try {
      const { agentApi } = await import('@/api')
      await agentApi.rollbackChanges(storyId(), activeConversationId.value ?? undefined)
      pendingChanges.value = []
      uni.showToast({ title: '已撤回变更', icon: 'success' })
    } catch (e) {
      uni.showToast({ title: '撤回失败', icon: 'none' })
    }
  }

  function clearMessages() {
    messages.value = []
    streamingContent.value = ''
    pendingChanges.value = []
  }

  return {
    messages,
    streaming,
    streamingContent,
    pendingChanges,
    activeConversationId,
    sendMessage,
    loadPendingChanges,
    confirmChanges,
    rollbackChanges,
    clearMessages,
    stopStreaming: stop
  }
}
