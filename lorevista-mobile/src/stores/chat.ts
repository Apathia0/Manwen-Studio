import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chaptersApi } from '@/api'
import { useSSE } from '@/composables/useSSE'
import { BASE_URL } from '@/utils/constants'
import { getToken } from '@/utils/storage'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const streamingContent = ref('')
  let sseHandle: ReturnType<typeof useSSE> | null = null

  function loadHistory(historyMessages: { role: string; content: string }[]) {
    messages.value = historyMessages.map((m, i) => ({
      id: `history-${i}`,
      role: m.role as 'user' | 'assistant',
      content: m.content
    }))
  }

  async function sendMessage(chapterId: number, content: string) {
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content
    }
    messages.value.push(userMsg)
    streamingContent.value = ''
    streaming.value = true

    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`

    const sse = useSSE()
    sseHandle = sse

    sse.start({
      url: chaptersApi.chatUrl(chapterId),
      headers,
      body: { content },
      onEvent: (event) => {
        if (event.type === 'token') {
          streamingContent.value += event.data.content
        } else if (event.type === 'done') {
          const assistantMsg: ChatMessage = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: event.data.content || streamingContent.value
          }
          messages.value.push(assistantMsg)
          streamingContent.value = ''
          streaming.value = false
        } else if (event.type === 'error') {
          streaming.value = false
          streamingContent.value = ''
        }
      },
      onError: () => {
        streaming.value = false
        streamingContent.value = ''
      },
      onComplete: () => {
        streaming.value = false
      }
    })
  }

  function stopStreaming() {
    sseHandle?.stop()
    streaming.value = false
    if (streamingContent.value) {
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: streamingContent.value
      }
      messages.value.push(assistantMsg)
      streamingContent.value = ''
    }
  }

  function clearMessages() {
    messages.value = []
    streamingContent.value = ''
  }

  return {
    messages,
    streaming,
    streamingContent,
    loadHistory,
    sendMessage,
    stopStreaming,
    clearMessages
  }
})
