import { useEffect, useState } from 'react';
import { RefreshCw, Pencil, Check, X, Sparkles } from 'lucide-react';
import { regenerateTags, updateStory } from '../../api';
import type { Tags } from '../../api';

interface Props {
  tags: Tags | null;
  storyId: number;
  onUpdate: () => void | Promise<void>;
}

const TAG_ENTRIES: { key: keyof Tags; label: string; color: string }[] = [
  { key: 'type', label: '类型', color: 'bg-blue-50 text-blue-700 border-blue-200' },
  { key: 'theme', label: '主题', color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  { key: 'style', label: '风格', color: 'bg-amber-50 text-amber-700 border-amber-200' },
  { key: 'audience', label: '受众', color: 'bg-violet-50 text-violet-700 border-violet-200' },
];

export default function TagSection({ tags, storyId, onUpdate }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingKey, setEditingKey] = useState<keyof Tags | null>(null);
  const [editValue, setEditValue] = useState('');
  const [localTags, setLocalTags] = useState<Tags | null>(null);

  useEffect(() => {
    setLocalTags(tags);
  }, [tags]);

  const displayTags = localTags ?? tags;
  const hasContent = displayTags && Object.values(displayTags).some((v) => v && v.trim());

  const handleRegenerate = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await regenerateTags(storyId);
      setLocalTags(result);
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '生成标签失败');
    } finally {
      setLoading(false);
    }
  };

  const startEdit = (key: keyof Tags) => {
    setEditingKey(key);
    setEditValue(displayTags?.[key] || '');
  };

  const saveEdit = async (key: keyof Tags) => {
    const nextTags = { ...(displayTags ?? {}), [key]: editValue || undefined };
    setLoading(true);
    setError('');
    try {
      await updateStory(storyId, { tags: nextTags });
      setLocalTags(nextTags);
      setEditingKey(null);
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '保存标签失败');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, key: keyof Tags) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void saveEdit(key);
    }
    if (e.key === 'Escape') {
      setEditingKey(null);
    }
  };

  if (!hasContent && !loading) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-slate-600">点击下方按钮，AI 将自动分析并生成故事的标签设定。</p>
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <RefreshCw size={13} className="animate-spin" /> : <Sparkles size={13} />}
          AI 生成标签
        </button>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {TAG_ENTRIES.map(({ key, label, color }) => {
        const value = displayTags?.[key];
        return (
          <div key={key} className="flex items-center gap-2.5">
            <span className="text-[11px] font-medium text-slate-500 w-8 shrink-0 text-right">{label}</span>
            <div className="flex-1 min-w-0">
              {editingKey === key ? (
                <div className="flex items-center gap-1">
                  <input
                    autoFocus
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, key)}
                    placeholder="输入标签值"
                    className="w-full max-w-[180px] rounded-md border border-slate-200 bg-white px-2 py-1 text-xs
                               text-slate-700 placeholder-slate-400 outline-none focus:border-blue-400 transition-colors"
                  />
                  <button
                    onClick={() => void saveEdit(key)}
                    className="p-0.5 text-emerald-600 hover:text-emerald-500 transition-colors"
                    title="确认"
                  >
                    <Check size={12} />
                  </button>
                  <button
                    onClick={() => setEditingKey(null)}
                    className="p-0.5 text-slate-400 hover:text-slate-600 transition-colors"
                    title="取消"
                  >
                    <X size={12} />
                  </button>
                </div>
              ) : (
                <span
                  onClick={() => startEdit(key)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border cursor-pointer transition-opacity hover:opacity-80 ${color}`}
                  title="点击编辑"
                >
                  {value || '未设置'}
                  {value && <Pencil size={9} className="opacity-60" />}
                </span>
              )}
            </div>
          </div>
        );
      })}

      <div className="flex items-center gap-2 pt-1.5">
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          重新生成
        </button>
        {error && <span className="text-xs text-red-500">{error}</span>}
      </div>
    </div>
  );
}
