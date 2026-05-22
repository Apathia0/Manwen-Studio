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

const states = new Map<number, VideoGenState>();
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
    emit();
  },

  patch(shotId: number, p: Partial<VideoGenState>) {
    const cur = states.get(shotId);
    if (!cur) return;
    states.set(shotId, { ...cur, ...p, lastEventAt: Date.now() });
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
    if (states.delete(shotId)) emit();
  },

  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
};
