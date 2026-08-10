// Module-level store for ongoing manga generation state.
// Keyed by chapterId so state survives chapter switching in the UI.

export interface GenImage {
  image_number: number;
  image_path: string;
  prompt: string;
}

export interface GenState {
  active: boolean;
  current: number;
  total: number;
  statusMsg: string;
  images: GenImage[];
  errorMsg: string;
  lastEventAt: number;
}

const states = new Map<number, GenState>();
const listeners = new Set<() => void>();

// 快照缓存：useSyncExternalStore 要求 getSnapshot 每次渲染返回同一引用，
// 否则 React 会判定 store 持续变化导致无限重渲染。状态变更时（emit）失效重建。
let snapshotCache: Map<number, GenState> | null = null;

function emit() {
  snapshotCache = null;
  listeners.forEach((fn) => fn());
}

function dedupeImages(images: GenImage[]): GenImage[] {
  return [...images]
    .sort((a, b) => a.image_number - b.image_number)
    .filter((img, index, arr) => index === 0 || arr[index - 1].image_number !== img.image_number);
}

export const genStore = {
  get(chapterId: number): GenState | undefined {
    return states.get(chapterId);
  },
  start(chapterId: number, total = 10, seedImages: GenImage[] = []) {
    const images = dedupeImages(seedImages);
    states.set(chapterId, {
      active: true,
      current: images.length,
      total,
      statusMsg: '正在生成漫画...',
      images,
      errorMsg: '',
      lastEventAt: Date.now(),
    });
    emit();
  },
  patch(chapterId: number, p: Partial<GenState>) {
    const cur = states.get(chapterId);
    if (!cur) return;
    states.set(chapterId, { ...cur, ...p, lastEventAt: Date.now() });
    emit();
  },
  pushImage(chapterId: number, img: GenImage) {
    const cur = states.get(chapterId);
    if (!cur) return;
    const images = dedupeImages([...cur.images, img]);
    states.set(chapterId, {
      ...cur,
      current: Math.max(cur.current, img.image_number),
      images,
      lastEventAt: Date.now(),
    });
    emit();
  },
  finish(chapterId: number, errorMsg?: string) {
    const cur = states.get(chapterId);
    if (!cur) return;
    states.set(chapterId, { ...cur, active: false, errorMsg: errorMsg ?? cur.errorMsg });
    emit();
  },
  clear(chapterId: number) {
    if (states.delete(chapterId)) emit();
  },
  /** 返回当前全部漫画生成状态的快照（任务中心聚合用）。已缓存映射，变更时自动失效 */
  snapshot(): Map<number, GenState> {
    if (!snapshotCache) snapshotCache = new Map(states);
    return snapshotCache;
  },
  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
};
