import { ImagePlus, Loader2, Sparkles, Upload } from 'lucide-react';
import { memo, useRef, useState } from 'react';
import MediaImage from './shared/MediaImage';
import {
  adjustStoryCover,
  coverImageUrl,
  generateStoryCover,
  uploadStoryCover,
  type Story,
} from '../api';

interface Props {
  story: Story;
  onUpdated?: () => void | Promise<void>;
}

export default memo(function StoryCoverCard({ story, onUpdated }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState<'generate' | 'adjust' | 'upload' | null>(null);
  const [error, setError] = useState('');

  const coverUrl = coverImageUrl(story.cover_image);

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
        await uploadStoryCover(story.id, b64);
        await onUpdated?.();
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
    try {
      await generateStoryCover(story.id, instruction.trim());
      await onUpdated?.();
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
    try {
      await adjustStoryCover(story.id, instruction.trim());
      await onUpdated?.();
    } catch (err: any) {
      setError(err?.message || '调整封面失败');
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-[linear-gradient(135deg,_#ffffff_0%,_#f5f9ff_100%)] p-4 shadow-[0_8px_20px_rgba(59,130,246,0.06)]">
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleUploadFile}
      />
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <ImagePlus size={16} className="text-[#2563eb]" />
        小说封面
      </div>

      <div className="mt-3 grid gap-4 lg:grid-cols-[220px,minmax(0,1fr)]">
        <div className="overflow-hidden rounded-2xl border border-[#d7e3f4] bg-[#eef4ff]">
          {coverUrl ? (
            <MediaImage src={coverUrl} alt={story.title} className="h-[300px] w-full object-cover" />
          ) : (
            <div className="flex h-[300px] items-center justify-center px-6 text-center text-sm text-slate-400">
              还没有封面。可以根据作品摘要一键生成，也可以手动上传。
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3">
          <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3 text-xs leading-6 text-slate-500">
            系统会基于作品摘要、大纲和核心设定生成竖版小说封面。AI 生成和调整都会消耗平台图片配额，手动上传不会消耗。
          </div>

          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={5}
            placeholder="可选：补充封面要求，例如“突出女主、冷色调、都市霓虹感”或“把人物改成更年轻、减少背景元素”。"
            className="w-full resize-none rounded-2xl border border-[#d7e3f4] bg-[#fcfdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:ring-4 focus:ring-[#dbeafe]"
          />

          {error ? <div className="text-xs text-rose-600">{error}</div> : null}

          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => void handleGenerate()}
              disabled={loading !== null}
              className="inline-flex items-center gap-2 rounded-2xl bg-[#2563eb] px-4 py-2.5 text-sm font-medium text-white shadow-[0_10px_24px_rgba(37,99,235,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading === 'generate' ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              生成封面
            </button>
            <button
              onClick={() => void handleAdjust()}
              disabled={loading !== null || !story.cover_image}
              className="inline-flex items-center gap-2 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading === 'adjust' ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              调整封面
            </button>
            <button
              onClick={handleUploadClick}
              disabled={loading !== null}
              className="inline-flex items-center gap-2 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading === 'upload' ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
              上传封面
            </button>
          </div>
        </div>
      </div>
    </div>
  );
})
