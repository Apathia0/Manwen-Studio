import { useEffect, useMemo, useState } from 'react';
import { generateScreenplay, listScreenplayScenes, type ScriptScene } from '../api';

interface Props {
  chapterId?: number | null;
  chapterContent?: string | null;
  scenes: ScriptScene[];
  screenplay: string;
  onScenesChange: (scenes: ScriptScene[]) => void;
  onScreenplayChange: (text: string) => void;
  onSceneSelect: (scene: ScriptScene) => void;
}

export default function ScreenplayPanel({
  chapterId,
  chapterContent,
  scenes,
  screenplay,
  onScenesChange,
  onScreenplayChange,
  onSceneSelect,
}: Props) {
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const contentReady = !!chapterContent?.trim();
  const contentPreview = useMemo(() => {
    const text = (chapterContent || '').trim();
    if (!text) return '';
    return text.length > 120 ? `${text.slice(0, 120)}...` : text;
  }, [chapterContent]);

  useEffect(() => {
    setError(null);
    setNotice(null);
  }, [chapterId]);

  useEffect(() => {
    if (!chapterId) return;
    if (screenplay || scenes.length > 0) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    listScreenplayScenes(chapterId)
      .then((result) => {
        if (cancelled) return;
        onScreenplayChange(result.screenplay || '');
        onScenesChange(result.scenes || []);
        if (result.screenplay || (result.scenes?.length || 0) > 0) {
          setNotice(`已加载该章节的既有剧本，共 ${result.scenes.length} 个场次。`);
        }
      })
      .catch(() => {
        if (!cancelled) setNotice(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [chapterId, screenplay, scenes.length, onScenesChange, onScreenplayChange]);

  async function handleGenerate() {
    if (!chapterId || !contentReady) return;
    setGenerating(true);
    setError(null);
    setNotice('正在根据当前正文生成影视剧本和场次...');
    try {
      const result = await generateScreenplay(chapterId, {
        mode: 'from_chapter',
        style: 'cinematic',
        scene_count_hint: 5,
        regenerate: true,
      });
      onScreenplayChange(result.screenplay);
      onScenesChange(result.scenes);
      setNotice(`剧本已生成，共 ${result.scenes.length} 个场次。点击下方任一场次即可继续拆解镜头。`);
    } catch (err: any) {
      setError(err.message || '生成剧本失败');
      setNotice(null);
    } finally {
      setGenerating(false);
    }
  }

  async function handleLoad() {
    if (!chapterId) return;
    setLoading(true);
    setError(null);
    setNotice('正在加载已生成的场次...');
    try {
      const result = await listScreenplayScenes(chapterId);
      onScreenplayChange(result.screenplay);
      onScenesChange(result.scenes);
      setNotice(
        result.scenes.length > 0
          ? `已加载 ${result.scenes.length} 个场次，点击场次即可进入镜头拆解。`
          : '当前章节还没有已生成的剧本，请先点击“生成剧本”。',
      );
    } catch (err: any) {
      setError(err.message || '加载场次失败');
      setNotice(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-slate-900">影视剧本</h3>
          <p className="mt-1 text-sm text-slate-500">先读取本章正文，再生成剧本与场次，最后进入镜头拆解。</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={handleLoad}
            disabled={loading || generating || !chapterId}
            className="rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm text-slate-700 hover:bg-white disabled:opacity-60"
          >
            {loading ? '加载中...' : '加载场次'}
          </button>
          <button
            onClick={handleGenerate}
            disabled={generating || loading || !contentReady}
            className="rounded-xl bg-[#2563eb] px-4 py-2 text-sm text-white disabled:opacity-60"
          >
            {generating ? '生成中...' : screenplay ? '重新生成剧本' : '生成剧本'}
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-medium text-slate-700">当前正文基础</div>
          {!contentReady && <span className="text-xs text-amber-600">本章还没有正文，先回到“正文内容”生成或编辑正文</span>}
        </div>
        {contentReady ? (
          <p className="text-sm leading-6 text-slate-600">{contentPreview}</p>
        ) : (
          <p className="text-sm text-slate-400">缺少章节正文，无法生成影视剧本。</p>
        )}
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

      {screenplay && (
        <div className="rounded-xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
          <div className="mb-2 text-sm font-medium text-slate-700">剧本全文</div>
          <pre className="whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{screenplay}</pre>
        </div>
      )}

      {scenes.length > 0 && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-medium text-slate-700">场次列表（{scenes.length} 场）</h4>
            <span className="text-xs text-slate-400">点击任一场次进入镜头拆解</span>
          </div>
          <div className="space-y-3">
            {scenes.map((scene) => (
              <div
                key={scene.id || scene.scene_number}
                onClick={() => onSceneSelect(scene)}
                className="cursor-pointer rounded-xl border border-[#d7e3f4] bg-white p-4 transition-colors hover:border-[#93c5fd] hover:bg-[#f8fbff]"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="text-sm font-medium text-slate-900">
                    场次 {scene.scene_number}: {scene.title}
                  </div>
                  <span className="text-xs text-slate-400">{scene.estimated_duration_seconds || '?'}s</span>
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {scene.location || '未明确地点'} · {scene.time_of_day || '白天'}
                </div>
                <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-600">{scene.summary}</div>
                {scene.characters.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {scene.characters.map((character, index) => (
                      <span key={`${character}-${index}`} className="rounded-full bg-[#eff6ff] px-2 py-0.5 text-xs text-[#2563eb]">
                        {character}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!screenplay && scenes.length === 0 && !generating && !loading && (
        <div className="py-12 text-center text-slate-400">
          <p className="text-sm">点击“生成剧本”把当前正文转换成影视剧本。</p>
          <p className="mt-2 text-xs">生成完成后，会在这里出现剧本全文和场次卡片，点击场次即可继续拆解镜头。</p>
        </div>
      )}
    </div>
  );
}
