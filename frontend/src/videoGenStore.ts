// Module-level store for ongoing asset generation state (video/storyboard/character/scene).
// Keyed by shotId + assetType so state survives shot switching and window close.

export type AssetType = 'video' | 'storyboard' | 'character' | 'scene';

export interface VideoGenState {
  active: boolean;           // Whether a generation is in progress
  jobId: number | null;      // Current job ID
  status: string;            // Current job status: pending/queued/running/succeeded/failed/cancelled
  progress: number;          // 0-100
  statusMsg: string;         // Human readable status message
  errorMsg: string;          // Error message if failed
  lastEventAt: number;       // Timestamp of last update
}

const STORAGE_KEY = 'video_gen_states';
const STATE_EXPIRY_MS = 24 * 60 * 60 * 1000; // 24小时

// 视频类型直接用 shotId 字符串（保持向后兼容），其他类型加 ":<type>" 后缀
function stateKey(shotId: number, type: AssetType = 'video'): string {
  return type === 'video' ? String(shotId) : `${shotId}:${type}`;
}

function loadPersistedStates(): Map<string, VideoGenState> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return new Map();

    const parsed = JSON.parse(stored);
    const now = Date.now();
    const states = new Map<string, VideoGenState>();

    for (const [key, state] of Object.entries(parsed)) {
      if (now - (state as VideoGenState).lastEventAt < STATE_EXPIRY_MS) {
        states.set(key, state as VideoGenState);
      }
    }

    return states;
  } catch {
    return new Map();
  }
}

function persistStates(states: Map<string, VideoGenState>): void {
  try {
    const obj: Record<string, VideoGenState> = {};
    states.forEach((state, key) => {
      obj[key] = state;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    // localStorage可能已满，忽略错误
  }
}

const states = loadPersistedStates();
const listeners = new Set<() => void>();

// 快照缓存：useSyncExternalStore 要求 getSnapshot 每次渲染返回同一引用，
// 否则 React 会判定 store 持续变化导致无限重渲染。状态变更时（emit）失效重建。
let snapshotCache: Map<string, VideoGenState> | null = null;

function emit() {
  snapshotCache = null;
  listeners.forEach((fn) => fn());
}

const DEFAULT_TYPE: AssetType = 'video';

export const videoGenStore = {
  get(shotId: number, type: AssetType = DEFAULT_TYPE): VideoGenState | undefined {
    return states.get(stateKey(shotId, type));
  },

  set(shotId: number, state: VideoGenState, type: AssetType = DEFAULT_TYPE) {
    states.set(stateKey(shotId, type), { ...state, lastEventAt: Date.now() });
    persistStates(states);
    emit();
  },

  patch(shotId: number, p: Partial<VideoGenState>, type: AssetType = DEFAULT_TYPE) {
    const key = stateKey(shotId, type);
    const cur = states.get(key);
    if (!cur) return;
    states.set(key, { ...cur, ...p, lastEventAt: Date.now() });
    persistStates(states);
    emit();
  },

  startJob(shotId: number, jobId: number, type: AssetType = DEFAULT_TYPE) {
    const msg = type === 'video' ? '正在提交视频任务...'
      : type === 'storyboard' ? '正在生成故事版...'
      : type === 'character' ? '正在生成角色资产...'
      : '正在生成场景...';
    states.set(stateKey(shotId, type), {
      active: true,
      jobId,
      status: 'pending',
      progress: 0,
      statusMsg: msg,
      errorMsg: '',
      lastEventAt: Date.now(),
    });
    persistStates(states);
    emit();
  },

  updateProgress: (shotId: number, status: string, progress: number, statusMsg: string, type: AssetType = DEFAULT_TYPE) => {
    videoGenStore.patch(shotId, { status, progress, statusMsg }, type);
  },

  markSucceeded: (shotId: number, type: AssetType = DEFAULT_TYPE) => {
    const msg = type === 'video' ? '视频生成完成'
      : type === 'storyboard' ? '故事版生成完成'
      : type === 'character' ? '角色资产生成完成'
      : '场景生成完成';
    videoGenStore.patch(shotId, { active: false, status: 'succeeded', progress: 100, statusMsg: msg }, type);
  },

  markFailed: (shotId: number, errorMsg: string, type: AssetType = DEFAULT_TYPE) => {
    const msg = type === 'video' ? '视频生成失败'
      : type === 'storyboard' ? '故事版生成失败'
      : type === 'character' ? '角色资产生成失败'
      : '场景生成失败';
    videoGenStore.patch(shotId, { active: false, status: 'failed', progress: 0, errorMsg, statusMsg: msg }, type);
  },

  clear(shotId: number, type: AssetType = DEFAULT_TYPE) {
    if (states.delete(stateKey(shotId, type))) {
      persistStates(states);
      emit();
    }
  },

  /** 清除指定镜头所有资产类型的生成状态 */
  clearAll(shotId: number) {
    const prefixs = [String(shotId), `${shotId}:`];
    let changed = false;
    for (const key of states.keys()) {
      if (key === prefixs[0] || key.startsWith(prefixs[1])) {
        states.delete(key);
        changed = true;
      }
    }
    if (changed) {
      persistStates(states);
      emit();
    }
  },

  cleanupExpired() {
    const now = Date.now();
    let changed = false;

    states.forEach((state, key) => {
      if (now - state.lastEventAt > STATE_EXPIRY_MS) {
        states.delete(key);
        changed = true;
      }
    });

    if (changed) {
      persistStates(states);
      emit();
    }
  },

  /** 返回当前全部视频类生成状态的快照（任务中心聚合用）。已缓存映射，变更时自动失效 */
  snapshot(): Map<string, VideoGenState> {
    if (!snapshotCache) snapshotCache = new Map(states);
    return snapshotCache;
  },

  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
};
