import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'
import type { AuthUser } from '@/api/types'
import { getToken, setToken, clearAuth } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const user = ref<AuthUser | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!token.value)

  async function login(email: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.login({ email, password })
      token.value = response.token
      setToken(response.token)
      user.value = response.user
    } finally {
      loading.value = false
    }
  }

  async function register(name: string, email: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.register({ name, email, password })
      token.value = response.token
      setToken(response.token)
      user.value = response.user
    } finally {
      loading.value = false
    }
  }

  async function fetchUser() {
    if (!token.value) return
    try {
      user.value = await authApi.getCurrentUser()
    } catch {
      logout()
    }
  }

  function logout() {
    token.value = null
    user.value = null
    clearAuth()
    uni.reLaunch({ url: '/pages/auth/login' })
  }

  async function checkSession() {
    if (token.value) {
      await fetchUser()
    }
  }

  return {
    token,
    user,
    loading,
    isLoggedIn,
    login,
    register,
    fetchUser,
    logout,
    checkSession
  }
})
