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
  { key: 'type', label: '类型', color: 'bg-blue-500/20 text-blue-300 border-blue-600/30' },
  { key: 'theme', label: '主题', color: 'bg-emerald-500/20 text-emerald-300 border-emerald-600/30' },
  { key: 'style', label: '风格', color: 'bg-amber-500/20 text-amber-300 border-amber-600/30' },
  { key: 'audience', label: '受众', color: 'bg-violet-500/20 text-violet-300 border-violet-600/30' },
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
      onUpdate();
    } catch (err: any) {
      setError(err.message || '生成失败');
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
      setError(err.message || '保存失败');
    } finally {
      setLoading(false);
    }
  };

  const cancelEdit = () => {
    setEditingKey(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent, key: keyof Tags) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void saveEdit(key);
    }
    if (e.key === 'Escape') {
      cancelEdit();
    }
  };

  if (!hasContent && !loading) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-gray-600">点击下方按钮，AI 将自动分析并生成故事的标签设定。</p>
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 border border-violet-700/40
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <RefreshCw size={13} className="animate-spin" />
          ) : (
            <Sparkles size={13} />
          )}
          AI 生成标签
        </button>
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {TAG_ENTRIES.map(({ key, label, color }) => {
        const value = displayTags?.[key];
        return (
          <div key={key} className="flex items-center gap-2.5">
            <span className="text-[11px] font-medium text-gray-500 w-8 shrink-0 text-right">{label}</span>
            <div className="flex-1 min-w-0">
              {editingKey === key ? (
                <div className="flex items-center gap-1">
                  <input
                    autoFocus
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, key)}
                    placeholder="输入标签值"
                    className="w-full max-w-[180px] bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs
                               text-gray-200 placeholder-gray-600 outline-none focus:border-violet-500 transition-colors"
                  />
                  <button
                    onClick={() => void saveEdit(key)}
                    className="p-0.5 text-emerald-400 hover:text-emerald-300 transition-colors"
                    title="确认"
                  >
                    <Check size={12} />
                  </button>
                  <button
                    onClick={cancelEdit}
                    className="p-0.5 text-gray-500 hover:text-gray-300 transition-colors"
                    title="取消"
                  >
                    <X size={12} />
                  </button>
                </div>
              ) : (
                <span
                  onClick={() => startEdit(key)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium
                              border cursor-pointer transition-opacity hover:opacity-80 ${color}`}
                  title="点击编辑"
                >
                  {value || '未设置'}
                  {value && <Pencil size={9} className="opacity-50" />}
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
                     bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 border border-gray-700
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          重新生成
        </button>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </div>
  );
}
