import { defineStore } from 'pinia'
import { ref } from 'vue'

export type AssetType = 'video' | 'storyboard' | 'character' | 'scene'

export interface VideoGenState {
  active: boolean
  jobId: number | null
  status: string
  progress: number
  statusMsg: string
  errorMsg: string
  lastEventAt: number
}

const STORAGE_KEY = 'video_gen_states'
const STATE_EXPIRY_MS = 24 * 60 * 60 * 1000

function stateKey(shotId: number, type: AssetType = 'video'): string {
  return type === 'video' ? String(shotId) : `${shotId}:${type}`
}

function loadPersistedStates(): Map<string, VideoGenState> {
  try {
    const stored = uni.getStorageSync(STORAGE_KEY)
    if (!stored) return new Map()

    const parsed = typeof stored === 'string' ? JSON.parse(stored) : stored
    const now = Date.now()
    const states = new Map<string, VideoGenState>()

    for (const [key, state] of Object.entries(parsed)) {
      if (now - (state as VideoGenState).lastEventAt < STATE_EXPIRY_MS) {
        states.set(key, state as VideoGenState)
      }
    }

    return states
  } catch {
    return new Map()
  }
}

function persistStates(states: Map<string, VideoGenState>): void {
  try {
    const obj: Record<string, VideoGenState> = {}
    states.forEach((state, key) => {
      obj[key] = state
    })
    uni.setStorageSync(STORAGE_KEY, JSON.stringify(obj))
  } catch {
    // 存储可能已满，忽略错误
  }
}

export const useVideoGenStore = defineStore('videoGen', () => {
  const states = ref(loadPersistedStates())

  function persist() {
    persistStates(states.value)
  }

  function get(shotId: number, type: AssetType = 'video'): VideoGenState | undefined {
    return states.value.get(stateKey(shotId, type))
  }

  function set(shotId: number, state: VideoGenState, type: AssetType = 'video') {
    states.value.set(stateKey(shotId, type), { ...state, lastEventAt: Date.now() })
    persist()
  }

  function patch(shotId: number, p: Partial<VideoGenState>, type: AssetType = 'video') {
    const key = stateKey(shotId, type)
    const cur = states.value.get(key)
    if (!cur) return
    states.value.set(key, { ...cur, ...p, lastEventAt: Date.now() })
    persist()
  }

  function startJob(shotId: number, jobId: number, type: AssetType = 'video') {
    const msg = type === 'video' ? '正在提交视频任务...'
      : type === 'storyboard' ? '正在生成故事版...'
      : type === 'character' ? '正在生成角色资产...'
      : '正在生成场景...'
    states.value.set(stateKey(shotId, type), {
      active: true,
      jobId,
      status: 'pending',
      progress: 0,
      statusMsg: msg,
      errorMsg: '',
      lastEventAt: Date.now(),
    })
    persist()
  }

  function updateProgress(shotId: number, status: string, progress: number, statusMsg: string, type: AssetType = 'video') {
    patch(shotId, { status, progress, statusMsg }, type)
  }

  function markSucceeded(shotId: number, type: AssetType = 'video') {
    const msg = type === 'video' ? '视频生成完成'
      : type === 'storyboard' ? '故事版生成完成'
      : type === 'character' ? '角色资产生成完成'
      : '场景生成完成'
    patch(shotId, { active: false, status: 'succeeded', progress: 100, statusMsg: msg }, type)
  }

  function markFailed(shotId: number, errorMsg: string, type: AssetType = 'video') {
    const msg = type === 'video' ? '视频生成失败'
      : type === 'storyboard' ? '故事版生成失败'
      : type === 'character' ? '角色资产生成失败'
      : '场景生成失败'
    patch(shotId, { active: false, status: 'failed', progress: 0, errorMsg, statusMsg: msg }, type)
  }

  function clear(shotId: number, type: AssetType = 'video') {
    if (states.value.delete(stateKey(shotId, type))) {
      persist()
    }
  }

  function clearAll(shotId: number) {
    const prefix = `${shotId}:`
    let changed = false
    for (const key of states.value.keys()) {
      if (key === String(shotId) || key.startsWith(prefix)) {
        states.value.delete(key)
        changed = true
      }
    }
    if (changed) persist()
  }

  function cleanupExpired() {
    const now = Date.now()
    let changed = false
    states.value.forEach((state, key) => {
      if (now - state.lastEventAt > STATE_EXPIRY_MS) {
        states.value.delete(key)
        changed = true
      }
    })
    if (changed) persist()
  }

  return {
    states,
    get,
    set,
    patch,
    startJob,
    updateProgress,
    markSucceeded,
    markFailed,
    clear,
    clearAll,
    cleanupExpired,
  }
})
