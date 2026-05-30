import { useState, type Dispatch, type SetStateAction } from 'react';
import { listShotClips, activateShotClip, type VideoShot, type RenderedClip, type VideoGenerationJob } from '../api';

interface Props {
  shots: VideoShot[];
  clips: RenderedClip[];
  activeClipId: number | null;
  jobs: VideoGenerationJob[];
  onClipsChange: Dispatch<SetStateAction<RenderedClip[]>>;
  onActiveClipChange: (clipId: number | null) => void;
}

export default function ClipTimelinePanel({
  shots,
  clips,
  activeClipId,
  jobs,
  onClipsChange,
  onActiveClipChange,
}: Props) {
  const [loadingShots, setLoadingShots] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  async function handleLoadClips(shotId: number) {
    setLoadingShots((prev) => new Set([...prev, shotId]));
    setError(null);

    try {
      const result = await listShotClips(shotId);
      onClipsChange((prev) => {
        const filtered = prev.filter((clip) => clip.shot_id !== shotId);
        return [...filtered, ...result.clips];
      });

      if (result.active_clip_id) {
        onActiveClipChange(result.active_clip_id);
      }
    } catch (err: any) {
      setError(err.message || '加载片段失败');
    } finally {
      setLoadingShots((prev) => {
        const next = new Set(prev);
        next.delete(shotId);
        return next;
      });
    }
  }

  async function handleActivateClip(shotId: number, clipId: number) {
    setError(null);

    try {
      const result = await activateShotClip(shotId, clipId);
      onActiveClipChange(result.active_clip_id);
      onClipsChange((prev) =>
        prev.map((clip) =>
          clip.shot_id === shotId
            ? {
                ...clip,
                is_active: clip.id === clipId,
              }
            : clip,
        ),
      );
    } catch (err: any) {
      setError(err.message || '切换片段失败');
    }
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h3 className="text-lg font-semibold text-slate-900">片段管理</h3>
        <p className="mt-1 text-sm text-slate-500">查看和管理每个镜头的视频片段版本</p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {shots.length === 0 ? (
        <div className="py-12 text-center text-slate-400">
          <p className="text-sm">请先生成镜头</p>
        </div>
      ) : (
        <div className="space-y-4">
          {shots.map((shot) => {
            const shotClips = clips.filter((clip) => clip.shot_id === shot.id);
            const shotJob = jobs.find((job) => job.shot_id === shot.id);

            return (
              <div key={shot.id || shot.shot_number} className="rounded-xl border border-[#d7e3f4] bg-white p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-900">
                      镜头 {shot.shot_number}: {shot.title}
                    </div>
                    <div className="text-xs text-slate-500">{shot.duration_seconds || '?'}s</div>
                  </div>
                  <button
                    onClick={() => handleLoadClips(shot.id!)}
                    disabled={loadingShots.has(shot.id!)}
                    className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white disabled:opacity-60"
                  >
                    {loadingShots.has(shot.id!) ? '加载中...' : '刷新'}
                  </button>
                </div>

                {shotClips.length > 0 ? (
                  <div className="space-y-2">
                    {shotClips.map((clip) => {
                      const isCurrent = activeClipId === clip.id || clip.is_active;

                      return (
                        <div
                          key={clip.id}
                          className={`rounded-lg border p-2 text-xs ${
                            isCurrent
                              ? 'border-[#93c5fd] bg-[#eff6ff]'
                              : 'border-[#e5edf8] bg-[#f8fbff]'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <span className="font-medium text-slate-700">v{clip.version}</span>
                              <span className="ml-2 text-slate-400">{clip.duration_seconds || '?'}s</span>
                              <span className="ml-2 text-slate-400">{clip.resolution || '?'}</span>
                            </div>
                            <div className="flex gap-2">
                              {!isCurrent && (
                                <button
                                  onClick={() => handleActivateClip(shot.id!, clip.id)}
                                  className="text-[#2563eb] hover:underline"
                                >
                                  设为当前
                                </button>
                              )}
                              {isCurrent && (
                                <span className="rounded-full bg-[#dbeafe] px-2 py-0.5 text-[10px] text-[#2563eb]">
                                  当前
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">
                    {shotJob
                      ? shotJob.status === 'succeeded'
                        ? '片段已就绪，刷新后加载'
                        : `任务状态: ${shotJob.status}`
                      : '暂无片段'}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
