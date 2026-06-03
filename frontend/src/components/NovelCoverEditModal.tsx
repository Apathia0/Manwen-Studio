import { Loader2, Sparkles, Upload, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  adjustStoryCover,
  coverImageUrl,
  generateStoryCover,
  uploadStoryCover,
  type Story,
} from '../api';

interface Props {
  story: Story;
  onClose: () => void;
  onUpdated: () => void | Promise<void>;
}

type LoadingAction = 'generate' | 'adjust' | 'upload' | null;

export default function NovelCoverEditModal({ story, onClose, onUpdated }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState<LoadingAction>(null);
  const [error, setError] = useState('');
  const [zoom, setZoom] = useState<1 | 1.35 | 1.7>(1.35);
  const [currentCover, setCurrentCover] = useState(story.cover_image);
  const [imageLoaded, setImageLoaded] = useState(false);

  const coverUrl = coverImageUrl(currentCover);

  const handleUploadClick = () => fileRef.current?.click();

  const handleUploadFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setLoading('upload');
    setError('');
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const b64 = String(reader.result || '').split(',')[1] || '';
        const result = await uploadStoryCover(story.id, b64);
        setCurrentCover(result);
        await onUpdated();
      } catch (err: any) {
        setError(err?.message || '上传封面失败');
      } finally {
        setLoading(null);
        event.target.value = '';
      }
    };
    reader.onerror = () => {
      setError('读取图片失败');
      setLoading(null);
      event.target.value = '';
    };
    reader.readAsDataURL(file);
  };

  const handleGenerate = async () => {
    setLoading('generate');
    setError('');
    setImageLoaded(false);
    try {
      const result = await generateStoryCover(story.id, instruction.trim());
      setCurrentCover(result.cover_image);
      await onUpdated();
    } catch (err: any) {
      setError(err?.message || '生成封面失败');
    } finally {
      setLoading(null);
    }
  };

  const handleAdjust = async () => {
    if (!instruction.trim()) {
      setError('请先输入调整要求');
      return;
    }
    setLoading('adjust');
    setError('');
    setImageLoaded(false);
    try {
      const result = await adjustStoryCover(story.id, instruction.trim());
      setCurrentCover(result.cover_image);
      await onUpdated();
    } catch (err: any) {
      setError(err?.message || '调整封面失败');
    } finally {
      setLoading(null);
    }
  };

  const handleOneClickGenerate = async () => {
    setInstruction('');
    setLoading('generate');
    setError('');
    setImageLoaded(false);
    try {
      const result = await generateStoryCover(story.id, '');
      setCurrentCover(result.cover_image);
      await onUpdated();
    } catch (err: any) {
      setError(err?.message || '一键生成封面失败');
    } finally {
      setLoading(null);
    }
  };

  const previewImageClass =
    zoom === 1
      ? 'max-w-[92%] max-h-none'
      : zoom === 1.35
        ? 'max-w-none w-[780px]'
        : 'max-w-none w-[940px]';

  const modal = (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">
              小说封面编辑 — {story.title}
            </div>
            <div className="mt-1 text-sm text-slate-500">
              左侧查看成品效果，右侧编写封面说明或一键从作品摘要生成。
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200"
          >
            <X size={18} />
          </button>
        </div>

        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
          <div className="relative overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
            <div className="mb-4 flex items-center justify-between text-white/80">
              <div className="text-sm font-medium">封面效果预览</div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-white/60">缩放</span>
                {[1, 1.35, 1.7].map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setZoom(value as 1 | 1.35 | 1.7)}
                    className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                      zoom === value
                        ? 'bg-white text-slate-900'
                        : 'bg-white/10 text-white hover:bg-white/20'
                    }`}
                  >
                    {Math.round(value * 100)}%
                  </button>
                ))}
              </div>
            </div>
            <div className="relative mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              {coverUrl ? (
                <div className="relative rounded-[24px] bg-[#0b1220] p-4 shadow-2xl">
                  <img
                    src={coverUrl}
                    alt={`${story.title} 封面`}
                    onLoad={() => setImageLoaded(true)}
                    loading="lazy"
                    decoding="async"
                    className={`mx-auto h-auto max-h-[72vh] object-contain rounded-xl shadow-2xl transition-opacity ${previewImageClass} ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                  />
                  {!imageLoaded && (
                    <div className="flex min-h-[420px] min-w-[280px] items-center justify-center rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                      <Loader2 size={24} className="animate-spin" />
                    </div>
                  )}
                  {loading !== null && (
                    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-[24px] bg-black/70 backdrop-blur-sm">
                      <Loader2 size={40} className="animate-spin text-white" />
                      <span className="text-sm font-medium text-white/90">
                        {loading === 'generate' && 'AI 生成封面中...'}
                        {loading === 'adjust' && 'AI 调整封面中...'}
                        {loading === 'upload' && '上传封面中...'}
                      </span>
                      <span className="text-xs text-white/50">
                        {loading === 'generate' && '正在根据作品摘要生成专业封面'}
                        {loading === 'adjust' && '正在根据你的要求调整现有封面'}
                        {loading === 'upload' && '正在上传并处理封面图片'}
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="relative flex min-h-[420px] min-w-[280px] flex-col items-center justify-center gap-3 rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] px-8 text-center text-sm text-white/50">
                  {loading !== null ? (
                    <div className="flex flex-col items-center gap-3">
                      <Loader2 size={40} className="animate-spin text-white/80" />
                      <span className="text-sm font-medium text-white/80">
                        {loading === 'generate' && 'AI 生成封面中...'}
                        {loading === 'adjust' && 'AI 调整封面中...'}
                        {loading === 'upload' && '上传封面中...'}
                      </span>
                      <span className="text-xs text-white/40">
                        {loading === 'generate' && '正在根据作品摘要生成专业封面'}
                        {loading === 'adjust' && '正在根据你的要求调整现有封面'}
                        {loading === 'upload' && '正在上传并处理封面图片'}
                      </span>
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-white/20 px-8 py-6">
                      还没有封面
                      <br />
                      点击右侧「一键从作品摘要生成」
                      <br />
                      或手动编写说明生成/上传
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
            <div className="space-y-5">
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">智能封面生成</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">
                  系统会基于作品摘要、大纲和核心设定自动构建专业提示词，生成竖版小说封面。你也可以在下方补充自定义要求。
                  AI 生成会消耗平台图片配额，手动上传不消耗。
                </div>
              </div>

              <button
                type="button"
                onClick={() => void handleOneClickGenerate()}
                disabled={loading !== null}
                className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#2563eb] px-4 py-3 text-sm font-medium text-white shadow-[0_10px_24px_rgba(37,99,235,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading === 'generate' && !instruction.trim() ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Sparkles size={16} />
                )}
                {loading === 'generate' && !instruction.trim()
                  ? 'AI 生成中...'
                  : '一键从作品摘要生成专业封面'}
              </button>

              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  自定义封面说明
                </div>
                <textarea
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  rows={6}
                  className="w-full rounded-2xl border border-[#d7e3f4] bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
                  placeholder="可选：补充封面要求，例如「突出女主、冷色调、都市霓虹感」或「把人物改成更年轻、减少背景元素」。"
                />
              </div>

              {error ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-700">
                  {error}
                </div>
              ) : null}

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => void handleGenerate()}
                  disabled={loading !== null}
                  className="inline-flex items-center gap-2 rounded-2xl bg-[#2563eb] px-4 py-2.5 text-sm font-medium text-white shadow-[0_10px_24px_rgba(37,99,235,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading === 'generate' && instruction.trim() ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Sparkles size={15} />
                  )}
                  {loading === 'generate' && instruction.trim()
                    ? '生成中...'
                    : currentCover
                      ? '按说明重新生成'
                      : '按说明生成封面'}
                </button>
                <button
                  type="button"
                  onClick={() => void handleAdjust()}
                  disabled={loading !== null || !currentCover}
                  className="inline-flex items-center gap-2 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading === 'adjust' ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Sparkles size={15} />
                  )}
                  {loading === 'adjust' ? '调整中...' : '调整现有封面'}
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleUploadFile}
                />
                <button
                  type="button"
                  onClick={handleUploadClick}
                  disabled={loading !== null}
                  className="inline-flex items-center gap-2 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading === 'upload' ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Upload size={15} />
                  )}
                  {loading === 'upload' ? '上传中...' : '上传封面'}
                </button>
              </div>

              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3 text-xs leading-6 text-slate-400">
                提示：「一键从作品摘要生成」会自动提取作品标题、摘要、核心卖点、节奏基调和大纲阶段信息，构造最适合该小说的专业封面提示词。
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
