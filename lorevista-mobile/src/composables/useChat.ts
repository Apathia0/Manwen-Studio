import { ref } from 'vue'
import { useSSE } from './useSSE'
import { getToken } from '@/utils/storage'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export function useChat(chapterId: () => number) {
  const { streaming, start, stop } = useSSE()
  const messages = ref<ChatMessage[]>([])
  const streamingContent = ref('')

  function sendMessage(content: string) {
    messages.value.push({ role: 'user', content })
    streamingContent.value = ''

    start({
      url: `/api/chapters/${chapterId()}/chat`,
      headers: {
        'Authorization': `Bearer ${getToken()}`
      },
      body: { content },
      onEvent: (event) => {
        if (event.type === 'token') {
          streamingContent.value += event.data.content
        } else if (event.type === 'done') {
          messages.value.push({ role: 'assistant', content: event.data.content })
          streamingContent.value = ''
        } else if (event.type === 'error') {
          uni.showToast({ title: event.data.error, icon: 'none' })
        }
      }
    })
  }

  function clearMessages() {
    messages.value = []
    streamingContent.value = ''
  }

  return {
    messages,
    streaming,
    streamingContent,
    sendMessage,
    clearMessages,
    stopStreaming: stop
  }
}
