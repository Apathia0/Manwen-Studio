import { getBackgroundTaskStatus, type BackgroundTaskStatus } from './api';
import { toast } from './lib/toast';
import { normalizeErrorMessage } from './lib/errors';

const STORAGE_PREFIX = 'storycanvas.mangaAssetBatchTask.v1.';
const POLL_INTERVAL_MS = 3000;
const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled', 'canceled']);

export interface MangaAssetBatchUpdate {
  chapterId: number;
  task: BackgroundTaskStatus;
}

type Listener = (update: MangaAssetBatchUpdate) => void;

const listeners = new Set<Listener>();
const taskByChapter = new Map<number, BackgroundTaskStatus>();
const monitorByChapter = new Map<number, ReturnType<typeof setTimeout>>();
const taskIdByChapter = new Map<number, string>();
const pollFailureCountByChapter = new Map<number, number>();

function storageKey(chapterId: number): string {
  return `${STORAGE_PREFIX}${chapterId}`;
}

function notify(update: MangaAssetBatchUpdate): void {
  taskByChapter.set(update.chapterId, update.task);
  listeners.forEach((listener) => listener(update));
}

function finishMonitor(chapterId: number, task: BackgroundTaskStatus): void {
  monitorByChapter.delete(chapterId);
  taskIdByChapter.delete(chapterId);
  localStorage.removeItem(storageKey(chapterId));
  pollFailureCountByChapter.delete(chapterId);

  const completed = Number(task.result_json?.completed ?? task.metadata_json?.completed ?? 0);
  const failed = Number(task.result_json?.failed ?? task.metadata_json?.failed ?? 0);
  if (task.status === 'succeeded' && completed > 0) {
    const suffix = failed > 0 ? `，${failed} 张失败` : '';
    toast.success(`漫画资产批量出图完成：成功 ${completed} 张${suffix}`);
  } else {
    toast.error(normalizeErrorMessage(task.error_message || task.message, '漫画资产批量出图失败，请重试'));
  }
}

async function poll(chapterId: number, taskId: string): Promise<void> {
  if (taskIdByChapter.get(chapterId) !== taskId) return;
  try {
    const task = await getBackgroundTaskStatus(taskId);
    pollFailureCountByChapter.delete(chapterId);
    if (taskIdByChapter.get(chapterId) !== taskId) return;
    notify({ chapterId, task });
    if (terminalStatuses.has(task.status)) {
      finishMonitor(chapterId, task);
      return;
    }
  } catch (error) {
    const failureCount = (pollFailureCountByChapter.get(chapterId) ?? 0) + 1;
    pollFailureCountByChapter.set(chapterId, failureCount);
    if (failureCount === 3) {
      toast.error(normalizeErrorMessage(error, '暂时无法获取漫画资产任务状态，系统将继续重试'));
    }
  }
  if (taskIdByChapter.get(chapterId) !== taskId) return;
  const timer = setTimeout(() => void poll(chapterId, taskId), POLL_INTERVAL_MS);
  monitorByChapter.set(chapterId, timer);
}

export function trackMangaAssetBatch(chapterId: number, taskId: string): void {
  const previousTimer = monitorByChapter.get(chapterId);
  if (previousTimer) clearTimeout(previousTimer);
  taskIdByChapter.set(chapterId, taskId);
  localStorage.setItem(storageKey(chapterId), taskId);
  void poll(chapterId, taskId);
}

export function getTrackedMangaAssetBatch(chapterId: number): BackgroundTaskStatus | null {
  return taskByChapter.get(chapterId) ?? null;
}

export function subscribeMangaAssetBatch(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function resumeTrackedTasks(): void {
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index);
    if (!key?.startsWith(STORAGE_PREFIX)) continue;
    const chapterId = Number(key.slice(STORAGE_PREFIX.length));
    const taskId = localStorage.getItem(key);
    if (Number.isInteger(chapterId) && chapterId > 0 && taskId) {
      trackMangaAssetBatch(chapterId, taskId);
    }
  }
}

if (typeof window !== 'undefined') resumeTrackedTasks();
