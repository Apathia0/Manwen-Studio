import { useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, Sparkles, Users } from 'lucide-react';
import { regenerateCharacters } from '../../api';
import type { Character } from '../../api';

interface Props {
  characters: Character[] | null;
  storyId: number;
  onUpdate: () => void | Promise<void>;
}

function CharacterCard({ character, defaultOpen }: { character: Character; defaultOpen: boolean }) {
  const [expanded, setExpanded] = useState(defaultOpen);
  const roleLabel = character.role || '未设定';
  const roleColor =
    character.role === '主角'
      ? 'text-amber-700 bg-amber-50 border-amber-200'
      : character.role === '反派'
        ? 'text-rose-700 bg-rose-50 border-rose-200'
        : character.role === '配角'
          ? 'text-blue-700 bg-blue-50 border-blue-200'
          : 'text-slate-600 bg-slate-100 border-slate-200';

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden bg-white">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          <Users size={13} className="text-slate-400 shrink-0" />
          <span className="text-sm font-medium text-slate-800 truncate">
            {character.name || '未命名角色'}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${roleColor}`}>
            {roleLabel}
          </span>
        </div>
        {expanded ? <ChevronDown size={13} className="text-slate-400 shrink-0" /> : <ChevronRight size={13} className="text-slate-400 shrink-0" />}
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-2.5 border-t border-slate-200">
          {character.arc && (
            <div className="space-y-1.5">
              {typeof character.arc.motivation === 'string' && character.arc.motivation && (
                <div>
                  <span className="text-[10px] font-medium text-slate-500">动机</span>
                  <p className="text-xs text-slate-700 mt-0.5 leading-relaxed">{character.arc.motivation}</p>
                </div>
              )}
              {typeof character.arc.fear === 'string' && character.arc.fear && (
                <div>
                  <span className="text-[10px] font-medium text-slate-500">恐惧</span>
                  <p className="text-xs text-slate-700 mt-0.5 leading-relaxed">{character.arc.fear}</p>
                </div>
              )}
            </div>
          )}

          {Array.isArray(character.relationships) && character.relationships.length > 0 && (
            <div>
              <span className="text-[10px] font-medium text-slate-500">关系</span>
              <div className="flex flex-wrap gap-1.5 mt-0.5">
                {character.relationships.map((rel, i) => (
                  <span key={i} className="inline-flex items-center gap-1 text-[10px] text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
                    {rel.character && <span className="text-slate-800">{String(rel.character)}</span>}
                    {rel.relationship && <span className="text-slate-500">· {String(rel.relationship)}</span>}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function CharacterSection({ characters, storyId, onUpdate }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedAll, setExpandedAll] = useState(true);

  const hasContent = characters && characters.length > 0;

  const handleRegenerate = async () => {
    setLoading(true);
    setError('');
    try {
      await regenerateCharacters(storyId);
      await onUpdate();
    } catch (err: any) {
      setError(err.message || '生成角色失败');
    } finally {
      setLoading(false);
    }
  };

  if (!hasContent && !loading) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-slate-600">点击下方按钮，AI 会根据故事描述生成角色设定。</p>
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200
                     disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <RefreshCw size={13} className="animate-spin" /> : <Sparkles size={13} />}
          AI 生成角色
        </button>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        {characters && <span className="text-xs text-slate-500">{characters.length} 个角色</span>}
        <div className="flex items-center gap-2">
          <button onClick={() => setExpandedAll(!expandedAll)} className="text-[11px] text-slate-500 hover:text-slate-700 transition-colors">
            {expandedAll ? '全部收起' : '全部展开'}
          </button>
          <button
            onClick={handleRegenerate}
            disabled={loading}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg
                       bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200
                       disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
            重新生成
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        {characters?.map((char, i) => (
          <CharacterCard key={i} character={char} defaultOpen={expandedAll} />
        ))}
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
