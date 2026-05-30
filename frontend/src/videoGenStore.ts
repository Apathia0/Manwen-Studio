// Module-level store for ongoing video generation state.
// Keyed by shotId so state survives shot switching in the UI.

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

function loadPersistedStates(): Map<number, VideoGenState> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return new Map();

    const parsed = JSON.parse(stored);
    const now = Date.now();
    const states = new Map<number, VideoGenState>();

    for (const [shotId, state] of Object.entries(parsed)) {
      if (now - (state as VideoGenState).lastEventAt < STATE_EXPIRY_MS) {
        states.set(Number(shotId), state as VideoGenState);
      }
    }

    return states;
  } catch {
    return new Map();
  }
}

function persistStates(states: Map<number, VideoGenState>): void {
  try {
    const obj: Record<number, VideoGenState> = {};
    states.forEach((state, shotId) => {
      obj[shotId] = state;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    // localStorage可能已满，忽略错误
  }
}

const states = loadPersistedStates();
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

export const videoGenStore = {
  get(shotId: number): VideoGenState | undefined {
    return states.get(shotId);
  },

  set(shotId: number, state: VideoGenState) {
    states.set(shotId, { ...state, lastEventAt: Date.now() });
    persistStates(states);
    emit();
  },

  patch(shotId: number, p: Partial<VideoGenState>) {
    const cur = states.get(shotId);
    if (!cur) return;
    states.set(shotId, { ...cur, ...p, lastEventAt: Date.now() });
    persistStates(states);
    emit();
  },

  startJob(shotId: number, jobId: number) {
    states.set(shotId, {
      active: true,
      jobId,
      status: 'pending',
      progress: 0,
      statusMsg: '正在提交视频任务...',
      errorMsg: '',
      lastEventAt: Date.now(),
    });
    persistStates(states);
    emit();
  },

  updateProgress(shotId: number, status: string, progress: number, statusMsg: string) {
    this.patch(shotId, { status, progress, statusMsg });
  },

  markSucceeded(shotId: number) {
    this.patch(shotId, { active: false, status: 'succeeded', progress: 100, statusMsg: '视频生成完成' });
  },

  markFailed(shotId: number, errorMsg: string) {
    this.patch(shotId, { active: false, status: 'failed', progress: 0, errorMsg, statusMsg: '视频生成失败' });
  },

  clear(shotId: number) {
    if (states.delete(shotId)) {
      persistStates(states);
      emit();
    }
  },

  cleanupExpired() {
    const now = Date.now();
    let changed = false;

    states.forEach((state, shotId) => {
      if (now - state.lastEventAt > STATE_EXPIRY_MS) {
        states.delete(shotId);
        changed = true;
      }
    });

    if (changed) {
      persistStates(states);
      emit();
    }
  },

  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
};
