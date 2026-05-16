import { useState, type Dispatch, type SetStateAction } from 'react';
import { renderShotVideo, getVideoJob, type VideoShot, type VideoGenerationJob, type RenderedClip } from '../api';

interface Props {
  shot: VideoShot | null;
  jobs: VideoGenerationJob[];
  clips: RenderedClip[];
  onJobsChange: Dispatch<SetStateAction<VideoGenerationJob[]>>;
  onClipsChange: Dispatch<SetStateAction<RenderedClip[]>>;
}

export default function VideoPanel({
  shot,
  jobs,
  clips,
  onJobsChange,
  onClipsChange,
}: Props) {
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRenderVideo() {
    if (!shot?.id) return;
    setRendering(true);
    setError(null);
    try {
      const result = await renderShotVideo(shot.id, {
        provider: 'sora',
        duration_seconds: shot.duration_seconds || 5,
        aspect_ratio: '16:9',
        fps: 24,
        use_reference_assets: false,
      });

      onJobsChange((prev) => [result.job, ...prev]);
      pollJobStatus(result.job.id);
    } catch (err: any) {
      setError(err.message || '提交视频任务失败');
    } finally {
      setRendering(false);
    }
  }

  function pollJobStatus(jobId: number) {
    const poll = async () => {
      try {
        const job = await getVideoJob(jobId);

        onJobsChange((prev) => prev.map((item) => (item.id === jobId ? job : item)));

        if (job.clip) {
          onClipsChange((prev) => {
            const exists = prev.find((clip) => clip.id === job.clip!.id);
            return exists ? prev : [...prev, job.clip!];
          });
        }

        if (job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled') {
          return;
        }

        setTimeout(poll, 3000);
      } catch {
        setTimeout(poll, 5000);
      }
    };

    setTimeout(poll, 3000);
  }

  const activeClip = clips.find((clip) => clip.is_active);

  if (!shot) {
    return (
      <div className="p-6">
        <h3 className="mb-4 text-sm font-semibold text-slate-700">视频预览</h3>
        <div className="flex h-48 items-center justify-center text-slate-400">
          <p className="text-xs">请选择一个镜头查看视频</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <h3 className="text-sm font-semibold text-slate-700">视频预览</h3>

      <div className="rounded-xl border border-[#d7e3f4] bg-white p-3">
        <div className="text-sm font-medium text-slate-900">
          镜头 {shot.shot_number}: {shot.title}
        </div>
        <div className="mt-1 text-xs text-slate-500">
          {shot.duration_seconds || '?'}s · {shot.shot_type || '中景'}
        </div>
      </div>

      <div className="flex aspect-video items-center justify-center rounded-xl border border-[#d7e3f4] bg-slate-100">
        {activeClip ? (
          <div className="text-center">
            <div className="mb-2 text-xs text-slate-500">视频片段已就绪</div>
            <div className="text-xs text-slate-400">路径: {activeClip.video_path}</div>
          </div>
        ) : (
          <div className="text-center text-slate-400">
            <div className="mb-2 text-3xl">🎬</div>
            <div className="text-xs">暂无视频</div>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </div>
      )}

      <button
        onClick={handleRenderVideo}
        disabled={rendering}
        className="w-full rounded-xl bg-[#2563eb] py-2 text-sm text-white disabled:opacity-60"
      >
        {rendering ? '提交中...' : '生成视频'}
      </button>

      {jobs.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-slate-500">任务列表</h4>
          <div className="space-y-2">
            {jobs.map((job) => (
              <div key={job.id} className="rounded-lg border border-[#d7e3f4] bg-white p-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className={jobStatusColor(job.status)}>{jobStatusLabel(job.status)}</span>
                  <span className="text-slate-400">{job.progress}%</span>
                </div>
                <div className="mt-1 text-slate-400">Provider: {job.provider}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {clips.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-slate-500">已生成片段</h4>
          <div className="space-y-2">
            {clips.map((clip) => (
              <div key={clip.id} className="rounded-lg border border-[#d7e3f4] bg-white p-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-700">v{clip.version}</span>
                  {clip.is_active && (
                    <span className="rounded-full bg-[#dbeafe] px-2 py-0.5 text-[10px] text-[#2563eb]">
                      当前
                    </span>
                  )}
                </div>
                <div className="mt-1 text-slate-400">
                  {clip.duration_seconds || '?'}s · {clip.resolution || '?'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function jobStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '等待中',
    queued: '排队中',
    running: '生成中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };

  return labels[status] || status;
}

function jobStatusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: 'text-slate-500',
    queued: 'text-amber-500',
    running: 'text-blue-500',
    succeeded: 'text-emerald-500',
    failed: 'text-rose-500',
    cancelled: 'text-slate-400',
  };

  return colors[status] || 'text-slate-500';
}
