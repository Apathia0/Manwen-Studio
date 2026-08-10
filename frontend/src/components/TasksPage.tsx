import { useSyncExternalStore } from 'react';
import { ListTodo, Image as ImageIcon, Clapperboard, Loader2, RefreshCw, CheckCircle2, XCircle } from 'lucide-react';
import { genStore, type GenState } from '../genStore';
import { videoGenStore, type VideoGenState, type AssetType } from '../videoGenStore';

const ASSET_LABELS: Record<AssetType, string> = {
  video: '视频',
  storyboard: '故事版',
  character: '角色',
  scene: '场景',
};

export type TaskEntry =
  | { kind: 'manga'; key: number; state: GenState }
  | { kind: 'video'; key: string; shotId: number; assetType: AssetType; state: VideoGenState };

function useGenSnapshot() {
  return useSyncExternalStore(
    (fn) => genStore.subscribe(fn),
    () => genStore.snapshot(),
  );
}

function useVideoSnapshot() {
  return useSyncExternalStore(
    (fn) => videoGenStore.subscribe(fn),
    () => videoGenStore.snapshot(),
  );
}

/** 聚合漫画 + 视频的生成任务（跨作品统一任务中心） */
export function useTaskAggregate(): {
  running: TaskEntry[];
  failed: TaskEntry[];
  done: TaskEntry[];
  all: TaskEntry[];
} {
  const mangaStates = useGenSnapshot();
  const videoStates = useVideoSnapshot();

  const mangaTasks: TaskEntry[] = [...mangaStates.entries()].map(([key, state]) => ({ kind: 'manga', key, state }));
  const videoTasks: TaskEntry[] = [...videoStates.entries()].map(([key, state]) => {
    const [shotIdStr, assetType] = key.split(':');
    return { kind: 'video', key, shotId: Number(shotIdStr), assetType: (assetType as AssetType) || 'video', state };
  });

  const all = [...mangaTasks, ...videoTasks];
  const running = all.filter((entry) => entry.state.active);
  const failed = all.filter((entry) => !entry.state.active && entry.state.errorMsg);
  const done = all.filter((entry) => !entry.state.active && !entry.state.errorMsg);
  return { running, failed, done, all };
}

type TasksPageProps = {
  onOpenWorkspace: (mode: 'manga' | 'video') => void;
};

/**
 * 跨作品任务中心：聚合漫画生成、视频/故事版/角色/场景生成任务。
 * 移动端卡片列表，桌面端表格。
 */
export function TasksPage({ onOpenWorkspace }: TasksPageProps) {
  const { running, failed } = useTaskAggregate();

  const renderEntry = (entry: TaskEntry) => {
    if (entry.kind === 'manga') {
      const { state } = entry;
      const isRunning = state.active;
      const percent = state.total > 0 ? Math.min(100, Math.round((state.current / state.total) * 100)) : 0;
      return (
        <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4 shadow-[0_6px_18px_rgba(59,130,246,0.06)]">
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isRunning ? 'bg-blue-50 text-[#1d4ed8]' : state.errorMsg ? 'bg-red-50 text-red-500' : 'bg-green-50 text-green-600'}`}>
              {isRunning ? <Loader2 size={20} className="animate-spin" /> : state.errorMsg ? <XCircle size={20} /> : <CheckCircle2 size={20} />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                <ImageIcon size={14} className="shrink-0 text-slate-400" />
                <span className="truncate">章节 {entry.key} 漫画生成</span>
              </div>
              <div className="mt-0.5 text-xs text-slate-500">{isRunning ? state.statusMsg : state.errorMsg || '已完成'}</div>
            </div>
            {isRunning && (
              <button
                type="button"
                onClick={() => onOpenWorkspace('manga')}
                className="shrink-0 rounded-xl border border-[#d7e3f4] px-3 py-1.5 text-xs font-medium text-[#1d4ed8] transition hover:bg-[#eef5ff]"
              >
                查看
              </button>
            )}
          </div>
          {isRunning && (
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#eef2f7]">
              <div className="h-full rounded-full bg-[#2563eb] transition-all duration-500" style={{ width: `${percent}%` }} />
            </div>
          )}
        </div>
      );
    }

    const { state } = entry;
    const isRunning = state.active;
    return (
      <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4 shadow-[0_6px_18px_rgba(59,130,246,0.06)]">
        <div className="flex items-center gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isRunning ? 'bg-blue-50 text-[#1d4ed8]' : state.errorMsg ? 'bg-red-50 text-red-500' : 'bg-green-50 text-green-600'}`}>
            {isRunning ? <Loader2 size={20} className="animate-spin" /> : state.errorMsg ? <XCircle size={20} /> : <CheckCircle2 size={20} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <Clapperboard size={14} className="shrink-0 text-slate-400" />
              <span className="truncate">
                镜头 {entry.shotId} · {ASSET_LABELS[entry.assetType]}生成
              </span>
            </div>
            <div className="mt-0.5 text-xs text-slate-500">{isRunning ? state.statusMsg : state.errorMsg || '已完成'}</div>
          </div>
          {isRunning && (
            <button
              type="button"
              onClick={() => onOpenWorkspace('video')}
              className="shrink-0 rounded-xl border border-[#d7e3f4] px-3 py-1.5 text-xs font-medium text-[#1d4ed8] transition hover:bg-[#eef5ff]"
            >
              查看
            </button>
          )}
        </div>
        {isRunning && (
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#eef2f7]">
            <div className="h-full rounded-full bg-[#2563eb] transition-all duration-500" style={{ width: `${Math.min(100, state.progress)}%` }} />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-5 lg:px-6">
      <div className="mb-4 flex items-center gap-2">
        <ListTodo size={20} className="text-[#1d4ed8]" />
        <h1 className="text-lg font-semibold text-slate-800">任务中心</h1>
      </div>

      {running.length === 0 && failed.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-[#d7e3f4] bg-white/60 py-16 text-center">
          <RefreshCw size={32} className="mb-3 text-slate-300" />
          <div className="text-sm font-medium text-slate-600">暂无进行中的任务</div>
          <div className="mt-1 text-xs text-slate-400">漫画或视频生成任务会实时显示在这里</div>
        </div>
      ) : (
        <div className="space-y-6">
          {running.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-slate-500">进行中（{running.length}）</h2>
              <div className="space-y-3">{running.map((entry) => <div key={`${entry.kind}-${entry.key}`}>{renderEntry(entry)}</div>)}</div>
            </section>
          )}
          {failed.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-slate-500">失败（{failed.length}）</h2>
              <div className="space-y-3">{failed.map((entry) => <div key={`${entry.kind}-${entry.key}`}>{renderEntry(entry)}</div>)}</div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
