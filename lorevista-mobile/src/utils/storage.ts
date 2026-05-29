import { STORAGE_KEYS } from './constants'

export function getStorage(key: string): string | null {
  try {
    return uni.getStorageSync(key) || null
  } catch {
    return null
  }
}

export function setStorage(key: string, value: string): void {
  try {
    uni.setStorageSync(key, value)
  } catch (e) {
    console.error('存储写入失败:', e)
  }
}

export function removeStorage(key: string): void {
  try {
    uni.removeStorageSync(key)
  } catch (e) {
    console.error('存储删除失败:', e)
  }
}

export function getToken(): string | null {
  return getStorage(STORAGE_KEYS.AUTH_TOKEN)
}

export function setToken(token: string): void {
  setStorage(STORAGE_KEYS.AUTH_TOKEN, token)
}

export function clearAuth(): void {
  removeStorage(STORAGE_KEYS.AUTH_TOKEN)
  removeStorage(STORAGE_KEYS.USER_INFO)
}
