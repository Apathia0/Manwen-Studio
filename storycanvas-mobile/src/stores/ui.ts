import { defineStore } from 'pinia'
import { ref } from 'vue'

interface ToastMessage {
  id: number
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
  duration: number
}

export const useUiStore = defineStore('ui', () => {
  const toasts = ref<ToastMessage[]>([])
  const globalLoading = ref(false)
  let toastId = 0

  function showToast(type: ToastMessage['type'], message: string, duration = 3000) {
    const id = ++toastId
    toasts.value.push({ id, type, message, duration })
    setTimeout(() => {
      toasts.value = toasts.value.filter(t => t.id !== id)
    }, duration)
  }

  function success(message: string) {
    showToast('success', message)
  }

  function error(message: string) {
    showToast('error', message, 5000)
  }

  function warning(message: string) {
    showToast('warning', message)
  }

  function info(message: string) {
    showToast('info', message)
  }

  function setLoading(value: boolean) {
    globalLoading.value = value
  }

  return {
    toasts,
    globalLoading,
    showToast,
    success,
    error,
    warning,
    info,
    setLoading
  }
})
