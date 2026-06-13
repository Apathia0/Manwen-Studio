import { useState, useRef, useEffect, type Dispatch, type SetStateAction } from 'react';
import { Film } from 'lucide-react';
import { apiHeaders, renderShotVideo, getVideoJob, type VideoShot, type VideoGenerationJob, type RenderedClip } from '../api';

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
  const [showUnlockWarning, setShowUnlockWarning] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);
  const [sseProgress, setSseProgress] = useState<{
    progress: number;
    stage: string;
    message: string;
    provider_status?: string | null;
    retry_count?: number;
    max_retries?: number;
    next_retry_at?: string | null;
  } | null>(null);

  // 用于组件卸载时清理轮询定时器
  const pollingRef = useRef<{ timeoutId: ReturnType<typeof setTimeout> | null; mounted: boolean }>({
    timeoutId: null,
    mounted: true,
  });

  useEffect(() => {
    pollingRef.current.mounted = true;
    return () => {
      pollingRef.current.mounted = false;
      if (pollingRef.current.timeoutId) {
        clearTimeout(pollingRef.current.timeoutId);
        pollingRef.current.timeoutId = null;
      }
    };
  }, []);

  async function handleRenderVideo(forceTextToVideo = false) {
    if (!shot?.id) return;
    setRendering(true);
    setError(null);
    setShowUnlockWarning(false);

    const hasStoryboard = !!shot.storyboard_asset_id;
    const inputMode = hasStoryboard && !forceTextToVideo
      ? 'image_to_video'
      : 'text_to_video';

    try {
      const result = await renderShotVideo(shot.id, {
        provider: 'sora',
        duration_seconds: shot.duration_seconds || 5,
        aspect_ratio: '16:9',
        fps: 24,
        use_reference_assets: false,
        input_mode: inputMode,
        source_storyboard_asset_id: hasStoryboard ? (shot.storyboard_asset_id ?? undefined) : undefined,
      });

      onJobsChange((prev) => [result.job, ...prev]);
      pollJobStatus(result.job.id);
    } catch (err: any) {
      setError(err.message || '提交视频任务失败');
    } finally {
      setRendering(false);
    }
  }

  function handleRenderClick() {
    if (!shot) return;
    const hasStoryboard = !!shot.storyboard_asset_id;
    const storyboardLocked = !!shot.storyboard_locked;

    if (!hasStoryboard) {
      void handleRenderVideo(true);
    } else if (!storyboardLocked) {
      setShowUnlockWarning(true);
    } else {
      void handleRenderVideo(false);
    }
  }

  const submitViaSSE = async () => {
    if (!shot) return;
    
    const response = await fetch(`/api/shots/${shot.id}/video/render-stream`, {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({
        provider: 'sora',
        duration_seconds: shot.duration_seconds || 5,
        aspect_ratio: '16:9',
        prompt: shot.video_prompt || '',
      }),
    });
    
    if (!response.ok) {
      console.error('SSE 连接失败');
      return;
    }
    
    setSseConnected(true);
    
    const reader = response.body?.getReader();
    if (!reader) return;
    
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      
      let currentEvent = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const parsed = JSON.parse(data);
            
            if (currentEvent === 'progress') {
              setSseProgress({
                progress: parsed.progress || 0,
                stage: parsed.stage || '',
                message: parsed.message || '',
                provider_status: parsed.provider_status ?? null,
                retry_count: parsed.retry_count ?? 0,
                max_retries: parsed.max_retries ?? 0,
                next_retry_at: parsed.next_retry_at ?? null,
              });
            } else if (currentEvent === 'done') {
              setSseProgress({ progress: 100, stage: 'done', message: '生成完成！' });
              if (parsed.job_id) {
                getVideoJob(parsed.job_id).then(更新任务 => {
                  onJobsChange((prev) => {
                    const 已存在 = prev.find(j => j.id === 更新任务.id);
                    return 已存在 ? prev.map(j => j.id === 更新任务.id ? 更新任务 : j) : [更新任务, ...prev];
                  });
                  if (更新任务.clip) {
                    onClipsChange((prev) => {
                      const 已存在 = prev.find(c => c.id === 更新任务.clip!.id);
                      return 已存在 ? prev : [...prev, 更新任务.clip!];
                    });
                  }
                }).catch(() => {});
              }
              setTimeout(() => {
                setSseConnected(false);
                setSseProgress(null);
              }, 3000);
            } else if (currentEvent === 'error') {
              setSseProgress({ progress: 0, stage: 'error', message: parsed.error || '生成失败' });
              setTimeout(() => {
                setSseConnected(false);
                setSseProgress(null);
              }, 5000);
            }
          } catch {
          }
        }
      }
    }
    
    setSseConnected(false);
  };

  function pollJobStatus(jobId: number) {
    let delay = 3000;
    const maxDelay = 30000;
    const maxRetries = 60;
    let attemptCount = 0;

    const poll = async () => {
      if (!pollingRef.current.mounted) return;

      attemptCount++;
      if (attemptCount > maxRetries) {
        console.error(`视频任务 ${jobId} 轮询已达最大次数 ${maxRetries}，停止轮询`);
        return;
      }

      try {
        const job = await getVideoJob(jobId);

        if (!pollingRef.current.mounted) return;

        onJobsChange((prev) => prev.map((item) => (item.id === jobId ? job : item)));

        if (job.clip) {
          onClipsChange((prev) => {
            const exists = prev.find((clip) => clip.id === job.clip!.id);
            return exists ? prev : [...prev, job.clip!];
          });
        }

        if (job.status === 'running' || job.status === 'queued') {
          delay = Math.min(delay * 1.5, maxDelay);
          pollingRef.current.timeoutId = setTimeout(poll, delay);
        } else {
          delay = 3000;
        }
      } catch (err) {
        console.error(`视频任务 ${jobId} 轮询出错:`, err);
        if (attemptCount >= maxRetries) return;
        pollingRef.current.timeoutId = setTimeout(poll, delay);
      }
    };

    pollingRef.current.timeoutId = setTimeout(poll, delay);
  }

  const activeClip = clips.find((clip) => clip.is_active);
  const hasStoryboard = !!shot?.storyboard_asset_id;
  const storyboardLocked = !!shot?.storyboard_locked;

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
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium text-slate-900">
              镜头 {shot.shot_number}: {shot.title}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {shot.duration_seconds || '?'}s · {shot.shot_type || '中景'}
              {shot.style_preset && <span> · {shot.style_preset}</span>}
            </div>
          </div>
          {storyboardLocked && (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
              分镜图已锁定
            </span>
          )}
        </div>
      </div>

      {!hasStoryboard && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          当前镜头还没有主分镜图，建议先在"镜头拆解"中生成并锁定分镜图。
          未锁定分镜图时生成视频将使用纯文生视频模式。
        </div>
      )}
      {hasStoryboard && !storyboardLocked && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          主分镜图尚未锁定。建议先锁定分镜图以确保角色和场景一致性。
        </div>
      )}

      <div className="flex aspect-video items-center justify-center overflow-hidden rounded-xl border border-[#d7e3f4] bg-black">
        {activeClip ? (
          <video
            src={activeClip.video_path}
            controls
            className="h-full w-full"
          >
            您的浏览器不支持视频播放
          </video>
        ) : (
          <div className="text-center text-slate-400">
            <div className="mb-2"><Film size={32} className="mx-auto text-slate-400" /></div>
            <div className="text-xs">暂无视频</div>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </div>
      )}

      {showUnlockWarning && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs">
          <div className="mb-3 font-medium text-amber-800">
            主分镜图尚未锁定，仍使用图生视频模式？
          </div>
          <p className="mb-3 text-amber-700">
            建议先在"镜头拆解"中锁定分镜图以确保角色和场景一致性。
            未锁定分镜图直接生成视频可能导致角色和场景不一致。
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setShowUnlockWarning(false);
                void handleRenderVideo(false);
              }}
              disabled={rendering}
              className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs text-white disabled:opacity-60"
            >
              {rendering ? '提交中...' : '仍使用图生视频'}
            </button>
            <button
              onClick={() => {
                setShowUnlockWarning(false);
                void handleRenderVideo(true);
              }}
              disabled={rendering}
              className="rounded-lg border border-amber-300 px-3 py-1.5 text-xs text-amber-700 disabled:opacity-60"
            >
              降级为文生视频
            </button>
            <button
              onClick={() => setShowUnlockWarning(false)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {sseConnected && sseProgress && (
        <div className="mb-4 p-3 bg-indigo-50 rounded-lg border border-indigo-200">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-indigo-700">
              {sseProgress.stage === 'submitting' ? '提交中...' :
               sseProgress.stage === 'submitted' ? '等待中...' :
               sseProgress.stage === 'generating' ? '生成中...' :
               sseProgress.stage === 'downloading' ? '下载中...' :
               sseProgress.stage === 'done' ? '完成！' :
               sseProgress.stage === 'error' ? '失败' :
               '进行中...'}
            </span>
            <span className="text-xs text-indigo-600">{sseProgress.progress}%</span>
          </div>
          <div className="w-full h-2 bg-indigo-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                sseProgress.stage === 'error' ? 'bg-red-500' :
                sseProgress.stage === 'done' ? 'bg-green-500' :
                'bg-indigo-500'
              }`}
              style={{ width: `${sseProgress.progress}%` }}
            />
          </div>
          {sseProgress.message && (
            <p className="text-xs text-indigo-500 mt-1">{sseProgress.message}</p>
          )}
          {(sseProgress.retry_count ?? 0) > 0 && (
            <p className="text-xs text-amber-600 mt-1">
              自动重试 {sseProgress.retry_count}/{sseProgress.max_retries ?? 0}
            </p>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleRenderClick}
          disabled={rendering}
          className={`flex-1 rounded-xl py-2 text-sm text-white disabled:opacity-60 ${
            hasStoryboard && storyboardLocked
              ? 'bg-[#2563eb]'
              : 'bg-slate-400'
          }`}
        >
          {rendering
            ? '提交中...'
            : !hasStoryboard
              ? '生成视频（文生视频）'
              : storyboardLocked
                ? '生成视频（图生视频）'
                : '生成视频（分镜图未锁定）'}
        </button>
        <button
          onClick={submitViaSSE}
          disabled={sseConnected || !shot}
          className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {sseConnected ? '生成中...' : 'SSE 生成'}
        </button>
      </div>

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
                <div className="mt-1 flex gap-2 text-slate-400">
                  <span>Provider: {job.provider}</span>
                  {job.provider_status && <span>· 上游：{job.provider_status}</span>}
                  {job.input_mode && <span>· {job.input_mode === 'image_to_video' ? '图生视频' : '文生视频'}</span>}
                </div>
                {job.message && (
                  <div className="mt-1 text-slate-500">{job.message}</div>
                )}
                {(job.retry_count ?? 0) > 0 && (
                  <div className="mt-1 text-amber-600">自动重试 {job.retry_count}/{job.max_retries ?? 0}</div>
                )}
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
                  {clip.style_preset && <span> · {clip.style_preset}</span>}
                  {clip.review_status && clip.review_status !== 'pending' && (
                    <span className="ml-1"> · {clip.review_status}</span>
                  )}
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
