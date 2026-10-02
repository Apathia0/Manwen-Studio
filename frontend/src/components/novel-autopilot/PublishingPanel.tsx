import { useState } from 'react';
import { Loader2, Sparkles, Tags, BookOpen, ToyBrick, NotebookText } from 'lucide-react';
import type { PublishingPackageResponse } from '../../api';

interface Props {
  package_?: PublishingPackageResponse | null;
  onGenerate: () => Promise<PublishingPackageResponse>;
}

export default function PublishingPanel({ package_, onGenerate }: Props) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PublishingPackageResponse | null>(package_ ?? null);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    setLoading(true);
    setError('');
    try {
      setResult(await onGenerate());
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : '生成失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <NotebookText size={16} className="text-blue-600" />
          投稿包装
        </h3>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-[#2563eb] text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)]
                     hover:bg-[#1d4ed8] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {loading ? '生成中...' : result ? '重新生成' : '生成投稿'}
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-600">{error}</div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="rounded-xl border border-[#d7e3f4] bg-white p-3">
            <h4 className="text-xs font-semibold text-blue-700 mb-2 flex items-center gap-1.5">
              <BookOpen size={13} />
              备选书名
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {result.titles?.map((t, i) => (
                <span key={i} className="inline-block rounded-md bg-blue-50 px-2 py-1 text-xs text-blue-800 font-medium">
                  {t}
                </span>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-[#d7e3f4] bg-white p-3">
            <h4 className="text-xs font-semibold text-blue-700 mb-1.5 flex items-center gap-1.5">
              <NotebookText size={13} />
              简介
            </h4>
            <p className="text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">{result.summary}</p>
          </div>

          <div className="rounded-xl border border-[#d7e3f4] bg-white p-3">
            <h4 className="text-xs font-semibold text-blue-700 mb-2 flex items-center gap-1.5">
              <Sparkles size={13} />
              核心卖点
            </h4>
            <ul className="space-y-1">
              {result.selling_points?.map((s, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs text-slate-700">
                  <span className="text-blue-500 mt-0.5 shrink-0">&#8226;</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-xl border border-[#d7e3f4] bg-white p-3">
            <h4 className="text-xs font-semibold text-blue-700 mb-2 flex items-center gap-1.5">
              <Tags size={13} />
              平台标签
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {result.platform_tags?.map((t, i) => (
                <span key={i} className="inline-block rounded-md bg-purple-50 px-2 py-1 text-xs text-purple-700">
                  #{t}
                </span>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-[#d7e3f4] bg-white p-3">
            <h4 className="text-xs font-semibold text-blue-700 mb-1.5 flex items-center gap-1.5">
              <ToyBrick size={13} />
              投稿附言
            </h4>
            <p className="text-xs text-slate-600 italic">{result.submission_notes}</p>
          </div>
        </div>
      )}

      {!result && !loading && (
        <div className="rounded-xl border border-dashed border-[#d7e3f4] bg-white/50 p-6 text-center">
          <NotebookText size={32} className="mx-auto text-slate-300 mb-2" />
          <p className="text-xs text-slate-500">生成面向网文平台的投稿包装信息</p>
        </div>
      )}
    </div>
  );
}
