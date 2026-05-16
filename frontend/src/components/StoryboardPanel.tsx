import { useMemo, useState } from 'react';
import { generateSceneShots, generateShotPrompts, type ScriptScene, type VideoShot } from '../api';

interface Props {
  scene: ScriptScene | null;
  shots: VideoShot[];
  onShotsChange: (shots: VideoShot[]) => void;
  onShotSelect: (shot: VideoShot) => void;
}

export default function StoryboardPanel({
  scene,
  shots,
  onShotsChange,
  onShotSelect,
}: Props) {
  const [generating, setGenerating] = useState(false);
  const [generatingPrompts, setGeneratingPrompts] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expandedShot, setExpandedShot] = useState<number | null>(null);

  const readyShotCount = useMemo(
    () => shots.filter((shot) => !!shot.video_prompt || shot.status === 'prompt_ready').length,
    [shots],
  );

  async function handleGenerateShots() {
    if (!scene?.id) return;
    setGenerating(true);
    setError(null);
    setNotice('正在根据场次生成镜头拆解...');
    try {
      const result = await generateSceneShots(scene.id, {
        style: 'cinematic',
        shot_count_hint: 4,
        duration_budget_seconds: scene.estimated_duration_seconds || 18,
      });
      onShotsChange(result.shots);
      if (result.shots.length > 0) {
        onShotSelect(result.shots[0]);
        setExpandedShot(result.shots[0].id ?? result.shots[0].shot_number);
      }
      setNotice(`镜头已生成，共 ${result.shots.length} 条。先生成提示词，再到右侧生成视频。`);
    } catch (err: any) {
      setError(err.message || '生成镜头失败');
      setNotice(null);
    } finally {
      setGenerating(false);
    }
  }

  async function handleGeneratePrompts(shot: VideoShot) {
    if (!shot.id) return;
    setGeneratingPrompts(shot.id);
    setError(null);
    setNotice(`正在为镜头 ${shot.shot_number} 生成提示词...`);
    try {
      const result = await generateShotPrompts(shot.id, {
        style: 'cinematic',
        provider: 'sora',
        include_references: true,
      });
      const nextShots = shots.map((item) => (item.id === shot.id ? result.shot : item));
      onShotsChange(nextShots);
      onShotSelect(result.shot);
      setExpandedShot(result.shot.id ?? result.shot.shot_number);
      setNotice(`镜头 ${shot.shot_number} 的提示词已生成，现在可以在右侧直接生成视频。`);
    } catch (err: any) {
      setError(err.message || '生成提示词失败');
      setNotice(null);
    } finally {
      setGeneratingPrompts(null);
    }
  }

  if (!scene) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <p className="text-sm">请先在“影视剧本”里选择一个场次</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-slate-900">
            场次 {scene.scene_number}: {scene.title}
          </h3>
          <p className="mt-1 text-sm leading-6 text-slate-500">{scene.summary}</p>
        </div>
        <button
          onClick={handleGenerateShots}
          disabled={generating}
          className="shrink-0 rounded-xl bg-[#2563eb] px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {generating ? '生成中...' : shots.length > 0 ? '重新生成镜头' : '生成镜头'}
        </button>
      </div>

      <div className="rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] p-4 text-sm text-slate-600">
        <div className="flex flex-wrap items-center gap-4">
          <span>地点：{scene.location || '未明确地点'}</span>
          <span>时间：{scene.time_of_day || '白天'}</span>
          <span>预计时长：{scene.estimated_duration_seconds || '?'}s</span>
          <span>已生成提示词：{readyShotCount}/{shots.length}</span>
        </div>
      </div>

      {notice && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          {notice}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {shots.length > 0 && (
        <div className="space-y-3">
          {shots.map((shot) => {
            const expanded = expandedShot === (shot.id ?? shot.shot_number);
            return (
              <div key={shot.id || shot.shot_number} className="rounded-xl border border-[#d7e3f4] bg-white">
                <div
                  onClick={() => setExpandedShot(expanded ? null : (shot.id ?? shot.shot_number))}
                  className="flex cursor-pointer items-center justify-between gap-4 p-4"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-slate-900">
                      镜头 {shot.shot_number}: {shot.title}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {shot.shot_type || 'medium'} · {shot.camera_angle || 'eye_level'} · {shot.duration_seconds || '?'}s
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        onShotSelect(shot);
                        setNotice(`已选中镜头 ${shot.shot_number}，右侧可查看并生成视频。`);
                      }}
                      className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white"
                    >
                      设为当前
                    </button>
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleGeneratePrompts(shot);
                      }}
                      disabled={generatingPrompts === shot.id}
                      className="rounded-lg bg-[#2563eb] px-2 py-1 text-xs text-white disabled:opacity-60"
                    >
                      {generatingPrompts === shot.id ? '生成中...' : shot.video_prompt ? '重生成提示词' : '生成提示词'}
                    </button>
                  </div>
                </div>

                {expanded && (
                  <div className="space-y-2 border-t border-[#d7e3f4] px-4 py-3 text-xs text-slate-600">
                    <div><span className="font-medium">构图：</span>{shot.composition || '-'}</div>
                    <div><span className="font-medium">动作：</span>{shot.action_description || '-'}</div>
                    <div><span className="font-medium">对白：</span>{shot.dialogue || '-'}</div>
                    <div><span className="font-medium">音效：</span>{shot.sound_design || '-'}</div>
                    {shot.video_prompt && (
                      <div>
                        <span className="font-medium">视频提示词：</span>
                        <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-[#f8fbff] p-2 text-xs">{shot.video_prompt}</pre>
                      </div>
                    )}
                    {shot.storyboard_prompt && (
                      <div>
                        <span className="font-medium">关键帧提示词：</span>
                        <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-[#f8fbff] p-2 text-xs">{shot.storyboard_prompt}</pre>
                      </div>
                    )}
                    <div className="pt-2 text-slate-400">状态：{shotStatusLabel(shot.status)}</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {shots.length === 0 && !generating && (
        <div className="py-12 text-center text-slate-400">
          <p className="text-sm">点击“生成镜头”将这个场次拆成可执行镜头。</p>
          <p className="mt-2 text-xs">生成完成后，建议先为镜头生成提示词，再到右侧生成视频。</p>
        </div>
      )}
    </div>
  );
}

function shotStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: '草稿',
    prompt_ready: '提示词已就绪',
    storyboard_ready: '关键帧已就绪',
    rendering: '渲染中',
    completed: '已完成',
    failed: '失败',
  };
  return labels[status] || status;
}
