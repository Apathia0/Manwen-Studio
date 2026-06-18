import { useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
  X,
  Save,
  Eye,
  Edit3,
  Tag,
  Users,
  BookOpen,
  FileText,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { updateStory, type Story, type Tags, type Character, type Outline, type BigFiveScores } from '../api';
import { toast } from '../lib/toast';

// ─── 类型定义 ──────────────────────────────────────────────────

interface Props {
  story: Story;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

type TabKey = 'description' | 'tags' | 'characters' | 'outline';

const TAB_CONFIG: { key: TabKey; label: string; icon: typeof Tag }[] = [
  { key: 'description', label: '故事描述', icon: FileText },
  { key: 'tags', label: '标签设定', icon: Tag },
  { key: 'characters', label: '角色设定', icon: Users },
  { key: 'outline', label: '故事大纲', icon: BookOpen },
];

// ─── 大五人格配置（复用自 types.ts） ──────────────────────────

const BIG_FIVE_META: { key: keyof BigFiveScores; label: string; color: string; hue: string }[] = [
  { key: 'O', label: '开放性', color: 'accent-violet', hue: '#8b5cf6' },
  { key: 'C', label: '尽责性', color: 'accent-blue', hue: '#60a5fa' },
  { key: 'E', label: '外向性', color: 'accent-amber', hue: '#f59e0b' },
  { key: 'A', label: '宜人性', color: 'accent-emerald', hue: '#34d399' },
  { key: 'N', label: '情绪性', color: 'accent-rose', hue: '#fb7185' },
];

const TAG_COLORS: Record<string, string> = {
  type: 'bg-blue-50 text-blue-700 border-blue-200',
  theme: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  style: 'bg-amber-50 text-amber-700 border-amber-200',
  audience: 'bg-violet-50 text-violet-700 border-violet-200',
};

const TAG_LABELS: Record<string, string> = {
  type: '类型',
  theme: '主题',
  style: '风格',
  audience: '受众',
};

const ROLE_COLORS: Record<string, string> = {
  '主角': 'text-amber-700 bg-amber-50 border-amber-200',
  '反派': 'text-rose-700 bg-rose-50 border-rose-200',
  '配角': 'text-blue-700 bg-blue-50 border-blue-200',
};

const ACT_BADGE_COLORS = [
  'bg-blue-50 text-blue-700 border-blue-200',
  'bg-sky-50 text-sky-700 border-sky-200',
  'bg-emerald-50 text-emerald-700 border-emerald-200',
  'bg-amber-50 text-amber-700 border-amber-200',
  'bg-violet-50 text-violet-700 border-violet-200',
];

// ─── 主组件 ──────────────────────────────────────────────────

export default function FrameworkEditorModal({ story, onClose, onSaved }: Props) {
  const [description, setDescription] = useState(story.description || '');
  const [tags, setTags] = useState<Tags>(story.tags || {});
  const [characters, setCharacters] = useState<Character[]>(story.characters || []);
  const [outline, setOutline] = useState<Outline>(story.outline || { three_acts: [], themes: [], foreshadowing: [] });
  const [activeTab, setActiveTab] = useState<TabKey>('description');
  const [saving, setSaving] = useState(false);

  const hasTags = useMemo(
    () => Object.values(tags).some((v) => typeof v === 'string' && v.trim()),
    [tags],
  );

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateStory(story.id, {
        description: description || undefined,
        tags,
        characters,
        outline,
      });
      toast.success('框架已更新');
      await onSaved();
      onClose();
    } catch (err: any) {
      toast.error(err.message || '保存框架失败');
    } finally {
      setSaving(false);
    }
  };

  const modal = (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[90vh] w-[min(1440px,94vw)] flex-col overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4 shrink-0">
          <div>
            <div className="text-lg font-semibold text-slate-900">
              框架编辑器 — {story.title}
            </div>
            <div className="mt-1 text-sm text-slate-500">
              左侧实时预览，右侧按模块编辑故事框架的各个部分。
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200"
          >
            <X size={18} />
          </button>
        </div>

        {/* ── Body: Two-panel layout ── */}
        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.3fr)_1fr]">
          {/* ══ Left: Live Preview (40%) ══ */}
          <div className="overflow-y-auto bg-[#f8f9f7] p-6">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-slate-600">
              <Eye size={16} className="text-[#2563eb]" />
              实时预览
            </div>

            {/* Description Preview */}
            <PreviewCard icon={FileText} label="故事描述" accent="blue" isEmpty={!description.trim()}>
              {description.trim() ? (
                <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                  {description}
                </p>
              ) : (
                <span className="text-xs text-slate-400 italic">暂无描述</span>
              )}
            </PreviewCard>

            {/* Tags Preview */}
            <PreviewCard icon={Tag} label="标签设定" accent="emerald" isEmpty={!hasTags}>
              {hasTags ? (
                <div className="flex flex-wrap gap-2">
                  {Object.entries(tags).map(([key, value]) => {
                    if (typeof value !== 'string' || !value.trim()) return null;
                    return (
                      <span
                        key={key}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border ${TAG_COLORS[key] || 'bg-slate-100 text-slate-600 border-slate-200'}`}
                      >
                        <span className="opacity-60">{TAG_LABELS[key] || key}</span>
                        <span>{value}</span>
                      </span>
                    );
                  })}
                </div>
              ) : (
                <span className="text-xs text-slate-400 italic">暂无标签</span>
              )}
            </PreviewCard>

            {/* Characters Preview */}
            <PreviewCard icon={Users} label="角色设定" accent="violet" isEmpty={!characters.length}>
              {characters.length > 0 ? (
                <div className="space-y-2">
                  {characters.map((char, i) => (
                    <CharacterPreviewCard key={i} character={char} />
                  ))}
                </div>
              ) : (
                <span className="text-xs text-slate-400 italic">暂无角色</span>
              )}
            </PreviewCard>

            {/* Outline Preview */}
            <PreviewCard icon={BookOpen} label="故事大纲" accent="amber" isEmpty={!outline.three_acts?.length}>
              {outline.three_acts && outline.three_acts.length > 0 ? (
                <div className="space-y-2">
                  {outline.three_acts.map((act: any, i: number) => {
                    const chapters = Array.isArray(act?.chapters) ? act.chapters : [];
                    const validChapters = chapters.filter((ch: any) => Number.isInteger(Number(ch?.chapter_number)));
                    const badgeColor = ACT_BADGE_COLORS[i % ACT_BADGE_COLORS.length];
                    return (
                      <div key={i} className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100">
                          <span className="text-xs font-semibold text-slate-700">
                            {act?.title || act?.name || `第 ${i + 1} 幕`}
                          </span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${badgeColor}`}>
                            {validChapters.length} 章
                          </span>
                        </div>
                        {act?.summary && (
                          <p className="px-3 pt-2 pb-1 text-[11px] text-slate-500 leading-relaxed line-clamp-2">
                            {act.summary}
                          </p>
                        )}
                        {validChapters.length > 0 && (
                          <div className="px-3 pb-2 pt-1 space-y-0.5">
                            {validChapters.slice(0, 5).map((ch: any, ci: number) => (
                              <div key={ci} className="flex items-center gap-1.5 text-[10px] text-slate-600">
                                <span className="text-slate-400 font-mono shrink-0">#{String(ch.chapter_number).padStart(2, '0')}</span>
                                <span className="truncate">{ch.title || `第 ${ch.chapter_number} 章`}</span>
                              </div>
                            ))}
                            {validChapters.length > 5 && (
                              <p className="text-[9px] text-slate-400">还有 {validChapters.length - 5} 章...</p>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <span className="text-xs text-slate-400 italic">暂无大纲</span>
              )}
            </PreviewCard>
          </div>

          {/* ══ Right: Tab Editor (60%) ══ */}
          <div className="flex flex-col overflow-hidden border-l border-[#e5edf8] bg-white">
            {/* Tab Navigation */}
            <div className="flex border-b border-[#e5edf8] bg-[#f8fbff] shrink-0">
              {TAB_CONFIG.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`flex items-center gap-1.5 px-5 py-3 text-xs font-medium border-b-2 transition-colors ${
                    activeTab === key
                      ? 'border-[#2563eb] text-[#2563eb] bg-white'
                      : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  <Icon size={14} />
                  {label}
                </button>
              ))}
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-y-auto p-5">
              {activeTab === 'description' && (
                <DescriptionTab value={description} onChange={setDescription} />
              )}
              {activeTab === 'tags' && (
                <TagsTab tags={tags} onChange={setTags} />
              )}
              {activeTab === 'characters' && (
                <CharactersTab characters={characters} onChange={setCharacters} />
              )}
              {activeTab === 'outline' && (
                <OutlineTab outline={outline} onChange={setOutline} />
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 border-t border-[#e5edf8] px-5 py-4 shrink-0 bg-[#f8fbff]">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-slate-600 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium text-white rounded-xl bg-[#2563eb] hover:bg-[#1d4ed8] shadow-[0_6px_16px_rgba(37,99,235,0.2)] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                <Save size={16} />
                {saving ? '保存中...' : '保存框架'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

// ─── Preview Card 子组件 ──────────────────────────────────────

function PreviewCard({
  icon: Icon,
  label,
  accent,
  isEmpty,
  children,
}: {
  icon: typeof FileText;
  label: string;
  accent: 'blue' | 'emerald' | 'violet' | 'amber';
  isEmpty: boolean;
  children: React.ReactNode;
}) {
  const accentBorders: Record<string, string> = {
    blue: 'border-l-blue-400',
    emerald: 'border-l-emerald-400',
    violet: 'border-l-violet-400',
    amber: 'border-l-amber-400',
  };

  const accentIcons: Record<string, string> = {
    blue: 'text-blue-500',
    emerald: 'text-emerald-500',
    violet: 'text-violet-500',
    amber: 'text-amber-500',
  };

  return (
    <div className={`mb-4 rounded-xl border border-[#d9dfd7] bg-white overflow-hidden ${isEmpty ? 'opacity-70' : ''}`}>
      <div className={`flex items-center gap-1.5 px-4 py-2.5 border-b border-[#d9dfd7] ${accentBorders[accent]} border-l-4`}>
        <Icon size={13} className={accentIcons[accent]} />
        <span className="text-xs font-semibold text-slate-700">{label}</span>
      </div>
      <div className="px-4 py-3">
        {children}
      </div>
    </div>
  );
}

// ─── 角色预览卡片（展开详情） ──────────────────────────────────

function CharacterPreviewCard({ character }: { character: Character }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-slate-800 truncate">
            {character.name || '未命名角色'}
          </span>
          {character.role && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${
                ROLE_COLORS[character.role] || 'text-slate-600 bg-slate-100 border-slate-200'
              }`}
            >
              {character.role}
            </span>
          )}
        </div>
        <ChevronDown
          size={12}
          className={`text-slate-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-100 space-y-2">
          {/* 大五人格 */}
          {character.big_five && Object.keys(character.big_five).length > 0 && (
            <div>
              <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">大五人格</span>
              <div className="mt-1 grid grid-cols-5 gap-1">
                {BIG_FIVE_META.map(({ key, label, hue }) => {
                  const rawVal = (character.big_five as any)?.[key] ?? (character.big_five as any)?.[key.toLowerCase()];
                  const numVal = typeof rawVal === 'number' ? Math.max(0, Math.min(100, rawVal > 10 ? rawVal : rawVal * 10)) : 50;
                  return (
                    <div key={key} className="flex flex-col items-center gap-0.5">
                      <span className="text-[8px] text-slate-400">{label}</span>
                      <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${numVal}%`, backgroundColor: hue, opacity: 0.7 }}
                        />
                      </div>
                      <span className="text-[8px] tabular-nums text-slate-500">{Math.round(numVal)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 弧光 */}
          {character.arc && (character.arc.motivation || character.arc.fear) && (
            <div className="space-y-1">
              {character.arc.motivation && (
                <div>
                  <span className="text-[10px] text-slate-400">动机</span>
                  <p className="text-[11px] text-slate-600 leading-relaxed line-clamp-2">{character.arc.motivation}</p>
                </div>
              )}
              {character.arc.fear && (
                <div>
                  <span className="text-[10px] text-slate-400">恐惧</span>
                  <p className="text-[11px] text-slate-600 leading-relaxed line-clamp-2">{character.arc.fear}</p>
                </div>
              )}
            </div>
          )}

          {/* 关系网络 */}
          {Array.isArray(character.relationships) && character.relationships.length > 0 && (
            <div>
              <span className="text-[10px] text-slate-400">关系</span>
              <div className="flex flex-wrap gap-1 mt-0.5">
                {character.relationships.slice(0, 4).map((rel, ri) => (
                  <span key={ri} className="text-[9px] text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
                    {rel.character}{rel.relationship ? `·${rel.relationship}` : ''}
                  </span>
                ))}
                {character.relationships.length > 4 && (
                  <span className="text-[9px] text-slate-400">+{character.relationships.length - 4}</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Description Tab ──────────────────────────────────────────

function DescriptionTab({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wide">故事描述</div>
        <p className="mb-3 text-[11px] text-slate-500 leading-relaxed">
          用一段话描述故事的核心设定、背景和主线。这段描述会影响所有 AI 生成的结果。
        </p>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={16}
        placeholder="输入故事描述..."
        className="w-full rounded-xl border border-[#d9dfd7] bg-[#fcfcfa] px-4 py-3 text-sm text-slate-800 placeholder-slate-400 outline-none resize-y focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] transition-colors"
      />
      <div className="text-[11px] text-slate-400 text-right">
        已输入 {value.length} 字
      </div>
    </div>
  );
}

// ─── Tags Tab ──────────────────────────────────────────────────

function TagsTab({
  tags,
  onChange,
}: {
  tags: Tags;
  onChange: (t: Tags) => void;
}) {
  const setTag = (key: keyof Tags, value: string) => {
    onChange({ ...tags, [key]: value || undefined });
  };

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wide">标签设定</div>
        <p className="mb-3 text-[11px] text-slate-500 leading-relaxed">
          定义故事的类型、主题、风格和受众定位，帮助 AI 更准确地生成符合期望的内容。
        </p>
      </div>

      {(['type', 'theme', 'style', 'audience'] as const).map((key) => {
        const value = typeof tags[key] === 'string' ? tags[key] : '';
        return (
          <div key={key}>
            <div className="flex items-center gap-2 mb-1.5">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${TAG_COLORS[key]}`}
              >
                {TAG_LABELS[key]}
              </span>
              <span className="text-[11px] text-slate-400">（{key}）</span>
            </div>
            <input
              value={value}
              onChange={(e) => setTag(key, e.target.value)}
              placeholder={`输入${TAG_LABELS[key]}...`}
              className="w-full rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-sm text-slate-800 placeholder-slate-400 outline-none focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] transition-colors"
            />
          </div>
        );
      })}
    </div>
  );
}

// ─── Characters Tab ────────────────────────────────────────────

function CharactersTab({
  characters,
  onChange,
}: {
  characters: Character[];
  onChange: (c: Character[]) => void;
}) {
  const addCharacter = () => {
    onChange([
      ...characters,
      { name: '', role: '', big_five: {}, arc: {}, relationships: [] },
    ]);
  };

  const updateCharacter = (index: number, char: Character) => {
    const next = [...characters];
    next[index] = char;
    onChange(next);
  };

  const removeCharacter = (index: number) => {
    onChange(characters.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="mb-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wide">角色设定</div>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            编辑故事中的角色，包括大五人格、角色弧光和关系网络。
          </p>
        </div>
        <button
          onClick={addCharacter}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#2563eb] text-white hover:bg-[#1d4ed8] transition-colors"
        >
          <Plus size={13} />
          添加角色
        </button>
      </div>

      {characters.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-[#d9dfd7] p-8 text-center text-sm text-slate-400">
          暂无角色，点击上方「添加角色」开始创建
        </div>
      ) : (
        <div className="space-y-3">
          {characters.map((char, i) => (
            <CharacterEditorCard
              key={i}
              character={char}
              index={i}
              onChange={(c) => updateCharacter(i, c)}
              onRemove={() => removeCharacter(i)}
            />
          ))}
        </div>
      )}

      {characters.length > 0 && (
        <div className="text-[11px] text-slate-400 text-right">
          共 {characters.length} 个角色
        </div>
      )}
    </div>
  );
}

function CharacterEditorCard({
  character,
  index,
  onChange,
  onRemove,
}: {
  character: Character;
  index: number;
  onChange: (c: Character) => void;
  onRemove: () => void;
}) {
  const [expanded, setExpanded] = useState(true);

  const setField = (field: keyof Character, value: any) => {
    onChange({ ...character, [field]: value });
  };

  const setBigFive = (trait: keyof BigFiveScores, value: number) => {
    onChange({
      ...character,
      big_five: { ...(character.big_five || {}), [trait]: value },
    });
  };

  const setArcField = (field: string, value: string) => {
    onChange({
      ...character,
      arc: { ...(character.arc || {}), [field]: value },
    });
  };

  const addRelationship = () => {
    const rels = Array.isArray(character.relationships) ? [...character.relationships] : [];
    rels.push({ character: '', relationship: '' });
    onChange({ ...character, relationships: rels });
  };

  const updateRelationship = (idx: number, field: string, value: string) => {
    const rels = Array.isArray(character.relationships) ? [...character.relationships] : [];
    if (!rels[idx]) return;
    rels[idx] = { ...rels[idx], [field]: value };
    onChange({ ...character, relationships: rels });
  };

  const removeRelationship = (idx: number) => {
    const rels = Array.isArray(character.relationships) ? [...character.relationships] : [];
    onChange({ ...character, relationships: rels.filter((_, i) => i !== idx) });
  };

  const roleColor = character.role
    ? ROLE_COLORS[character.role] || 'text-slate-600 bg-slate-100 border-slate-200'
    : 'text-slate-400 bg-slate-50 border-slate-200';

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      {/* Card Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-slate-400 hover:text-slate-600 transition-colors"
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <span className="text-xs font-medium text-slate-400 w-5 shrink-0">#{index + 1}</span>
        <input
          value={character.name || ''}
          onChange={(e) => setField('name', e.target.value)}
          placeholder="角色名称"
          className="flex-1 text-sm font-medium text-slate-800 bg-transparent outline-none placeholder-slate-400"
        />
        <select
          value={character.role || ''}
          onChange={(e) => setField('role', e.target.value)}
          className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium outline-none ${roleColor}`}
        >
          <option value="">选择角色</option>
          <option value="主角">主角</option>
          <option value="反派">反派</option>
          <option value="配角">配角</option>
        </select>
        <button
          onClick={onRemove}
          className="p-1 text-slate-400 hover:text-red-500 transition-colors"
          title="删除角色"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {expanded && (
        <div className="px-4 py-3 space-y-4">
          {/* 大五人格 */}
          <div>
            <div className="text-[11px] font-medium text-slate-500 mb-2">大五人格</div>
            <div className="grid grid-cols-5 gap-3">
              {BIG_FIVE_META.map(({ key, label, hue }) => {
                const val = character.big_five?.[key];
                const numVal = typeof val === 'number' ? val : 50;
                return (
                  <div key={key} className="flex flex-col items-center gap-1">
                    <span className="text-[10px] font-bold text-slate-500">{key}</span>
                    <div className="relative w-full h-20 bg-slate-100 rounded-lg overflow-hidden flex items-end">
                      <div
                        className="w-full rounded-lg transition-all duration-200"
                        style={{
                          height: `${numVal}%`,
                          backgroundColor: hue,
                          opacity: 0.7,
                        }}
                      />
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={numVal}
                      onChange={(e) => setBigFive(key, Number(e.target.value))}
                      className="w-full h-1 accent-[#2563eb]"
                    />
                    <span className="text-[10px] text-slate-500 tabular-nums">{numVal}</span>
                  </div>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5">
              {BIG_FIVE_META.map(({ key, label }) => (
                <span key={key} className="text-[10px] text-slate-400">{key}={label}</span>
              ))}
            </div>
          </div>

          {/* 角色弧光 */}
          <div>
            <div className="text-[11px] font-medium text-slate-500 mb-2">角色弧光</div>
            <div className="space-y-2">
              <div>
                <span className="text-[10px] text-slate-400">动机</span>
                <textarea
                  value={character.arc?.motivation || ''}
                  onChange={(e) => setArcField('motivation', e.target.value)}
                  rows={2}
                  placeholder="角色的核心动机..."
                  className="w-full rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-1.5 text-xs text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors resize-none mt-1"
                />
              </div>
              <div>
                <span className="text-[10px] text-slate-400">恐惧</span>
                <textarea
                  value={character.arc?.fear || ''}
                  onChange={(e) => setArcField('fear', e.target.value)}
                  rows={2}
                  placeholder="角色的深层恐惧..."
                  className="w-full rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-1.5 text-xs text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors resize-none mt-1"
                />
              </div>
            </div>
          </div>

          {/* 关系网络 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-medium text-slate-500">关系网络</span>
              <button
                onClick={addRelationship}
                className="inline-flex items-center gap-1 text-[10px] font-medium text-[#2563eb] hover:text-[#1d4ed8] transition-colors"
              >
                <Plus size={11} />
                添加关系
              </button>
            </div>
            {(!Array.isArray(character.relationships) || character.relationships.length === 0) ? (
              <p className="text-[11px] text-slate-400 italic">暂无关系</p>
            ) : (
              <div className="space-y-1.5">
                {character.relationships.map((rel, ri) => (
                  <div key={ri} className="flex items-center gap-2">
                    <input
                      value={rel.character || ''}
                      onChange={(e) => updateRelationship(ri, 'character', e.target.value)}
                      placeholder="角色名"
                      className="flex-1 rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-2.5 py-1.5 text-xs text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors"
                    />
                    <span className="text-[10px] text-slate-400">→</span>
                    <input
                      value={rel.relationship || ''}
                      onChange={(e) => updateRelationship(ri, 'relationship', e.target.value)}
                      placeholder="关系描述"
                      className="flex-[1.5] rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-2.5 py-1.5 text-xs text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors"
                    />
                    <button
                      onClick={() => removeRelationship(ri)}
                      className="p-1 text-slate-400 hover:text-red-500 transition-colors shrink-0"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Outline Tab ──────────────────────────────────────────────

function OutlineTab({
  outline,
  onChange,
}: {
  outline: Outline;
  onChange: (o: Outline) => void;
}) {
  const threeActs = Array.isArray(outline.three_acts) ? outline.three_acts : [];

  const setThreeActs = (acts: Record<string, any>[]) => {
    onChange({ ...outline, three_acts: acts });
  };

  const addAct = () => {
    const actNumber = threeActs.length + 1;
    setThreeActs([
      ...threeActs,
      {
        act: String(actNumber),
        title: `第 ${actNumber} 幕`,
        summary: '',
        chapters: [],
      },
    ]);
  };

  const updateAct = (index: number, act: Record<string, any>) => {
    const next = [...threeActs];
    next[index] = act;
    setThreeActs(next);
  };

  const removeAct = (index: number) => {
    setThreeActs(threeActs.filter((_, i) => i !== index));
  };

  const totalChapters = threeActs.reduce(
    (sum, act) => sum + (Array.isArray(act?.chapters) ? act.chapters.length : 0),
    0,
  );
  const allChapters = threeActs.flatMap((act: any) =>
    Array.isArray(act?.chapters) ? act.chapters : []
  );
  const globalMaxChapter = allChapters.length > 0
    ? Math.max(...allChapters.map((ch: any) => Number(ch?.chapter_number) || 0))
    : 0;
  const nextChapterNumber = globalMaxChapter + 1;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="mb-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wide">故事大纲</div>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            编辑分幕结构和每章的规划内容。你还可以在编辑器中添加新章节或删除已有章节。
          </p>
        </div>
        <button
          onClick={addAct}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#2563eb] text-white hover:bg-[#1d4ed8] transition-colors"
        >
          <Plus size={13} />
          添加幕
        </button>
      </div>

      {threeActs.length > 0 && (
        <div className="text-[11px] text-slate-400">
          共 {threeActs.length} 幕 · {totalChapters} 章
        </div>
      )}

      {threeActs.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-[#d9dfd7] p-8 text-center text-sm text-slate-400">
          暂无大纲，点击上方「添加幕」开始构建故事结构
        </div>
      ) : (
        <div className="space-y-4">
          {threeActs.map((act: any, i: number) => (
            <ActEditorCard
              key={i}
              act={act}
              index={i}
              onChange={(a) => updateAct(i, a)}
              onRemove={() => removeAct(i)}
              actColorIndex={i}
              nextChapterNumber={nextChapterNumber}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ActEditorCard({
  act,
  index,
  onChange,
  onRemove,
  actColorIndex,
  nextChapterNumber,
}: {
  act: Record<string, any>;
  index: number;
  onChange: (a: Record<string, any>) => void;
  onRemove: () => void;
  actColorIndex: number;
  nextChapterNumber?: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const chapters = Array.isArray(act.chapters) ? act.chapters : [];
  const badgeColor = ACT_BADGE_COLORS[actColorIndex % ACT_BADGE_COLORS.length];
  const borderColor = [
    'border-l-blue-400',
    'border-l-sky-400',
    'border-l-emerald-400',
    'border-l-amber-400',
    'border-l-violet-400',
  ][actColorIndex % 5];

  const setField = (field: string, value: any) => {
    onChange({ ...act, [field]: value });
  };

  const setChapters = (chs: Record<string, any>[]) => {
    onChange({ ...act, chapters: chs });
  };

  const addChapter = () => {
    const num = nextChapterNumber ?? (chapters.length > 0
      ? Math.max(...chapters.map((ch: any) => Number(ch?.chapter_number) || 0)) + 1
      : 1);
    setChapters([
      ...chapters,
      {
        chapter_number: num,
        title: `第 ${num} 章`,
        summary: '',
        key_events: [],
      },
    ]);
  };

  const updateChapter = (chIdx: number, chapter: Record<string, any>) => {
    const next = [...chapters];
    next[chIdx] = chapter;
    setChapters(next);
  };

  const removeChapter = (chIdx: number) => {
    setChapters(chapters.filter((_: any, i: number) => i !== chIdx));
  };

  return (
    <div className={`rounded-xl border border-slate-200 bg-white overflow-hidden ${borderColor} border-l-4`}>
      {/* Act Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-slate-400 hover:text-slate-600 transition-colors"
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${badgeColor}`}>
          第 {index + 1} 幕
        </span>
        <input
          value={act.title || ''}
          onChange={(e) => setField('title', e.target.value)}
          placeholder="幕标题"
          className="flex-1 text-sm font-medium text-slate-800 bg-transparent outline-none placeholder-slate-400"
        />
        <span className="text-[11px] text-slate-400 shrink-0">
          {chapters.length} 章
        </span>
        <button
          onClick={onRemove}
          className="p-1 text-slate-400 hover:text-red-500 transition-colors shrink-0"
          title="删除此幕"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {expanded && (
        <div className="px-4 py-3 space-y-3">
          {/* Act Summary */}
          <div>
            <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">概述</span>
            <textarea
              value={act.summary || ''}
              onChange={(e) => setField('summary', e.target.value)}
              rows={3}
              placeholder="此幕的概述..."
              className="w-full rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 text-xs text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors resize-none mt-1"
            />
          </div>

          {/* Chapters */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">章节列表</span>
              <button
                onClick={addChapter}
                className="inline-flex items-center gap-1 text-[10px] font-medium text-[#2563eb] hover:text-[#1d4ed8] transition-colors"
              >
                <Plus size={11} />
                添加章节
              </button>
            </div>

            {chapters.length === 0 ? (
              <p className="text-[11px] text-slate-400 italic py-2">暂无章节</p>
            ) : (
              <div className="space-y-2">
                {chapters.map((chapter: any, ci: number) => (
                  <ChapterEditorCard
                    key={ci}
                    chapter={chapter}
                    index={ci}
                    onChange={(ch) => updateChapter(ci, ch)}
                    onRemove={() => removeChapter(ci)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ChapterEditorCard({
  chapter,
  index,
  onChange,
  onRemove,
}: {
  chapter: Record<string, any>;
  index: number;
  onChange: (ch: Record<string, any>) => void;
  onRemove: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const setField = (field: string, value: any) => {
    onChange({ ...chapter, [field]: value });
  };

  const keyEvents = Array.isArray(chapter.key_events) ? chapter.key_events : [];

  const addKeyEvent = () => {
    setField('key_events', [...keyEvents, '']);
  };

  const updateKeyEvent = (ei: number, value: string) => {
    const next = [...keyEvents];
    next[ei] = value;
    setField('key_events', next);
  };

  const removeKeyEvent = (ei: number) => {
    setField('key_events', keyEvents.filter((_: any, i: number) => i !== ei));
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-[#fcfcfa] overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-slate-400 hover:text-slate-600 transition-colors"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <span className="text-[10px] text-slate-500 font-mono shrink-0">
          #{String(chapter.chapter_number || index + 1).padStart(2, '0')}
        </span>
        <input
          value={chapter.title || ''}
          onChange={(e) => setField('title', e.target.value)}
          placeholder="章节标题"
          className="flex-1 text-xs font-medium text-slate-700 bg-transparent outline-none placeholder-slate-400"
        />
        <button
          onClick={onRemove}
          className="p-0.5 text-slate-400 hover:text-red-500 transition-colors shrink-0"
          title="删除章节"
        >
          <X size={11} />
        </button>
      </div>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-slate-100 pt-2">
          <div>
            <span className="text-[10px] text-slate-400">章节摘要</span>
            <textarea
              value={chapter.summary || ''}
              onChange={(e) => setField('summary', e.target.value)}
              rows={2}
              placeholder="本章摘要..."
              className="w-full rounded-lg border border-[#d9dfd7] bg-white px-2.5 py-1.5 text-[11px] text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors resize-none mt-1"
            />
          </div>

          {/* 关键事件 */}
          <div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-400">关键事件</span>
              <button
                onClick={addKeyEvent}
                className="text-[10px] font-medium text-[#2563eb] hover:text-[#1d4ed8]"
              >
                + 添加
              </button>
            </div>
            {keyEvents.map((event: any, ei: number) => (
              <div key={ei} className="flex items-center gap-1.5 mt-1">
                <span className="text-[10px] text-slate-300">{ei + 1}.</span>
                <input
                  value={typeof event === 'string' ? event : ''}
                  onChange={(e) => updateKeyEvent(ei, e.target.value)}
                  placeholder="事件描述..."
                  className="flex-1 rounded border border-[#d9dfd7] bg-white px-2 py-1 text-[11px] text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors"
                />
                <button
                  onClick={() => removeKeyEvent(ei)}
                  className="p-0.5 text-slate-400 hover:text-red-500"
                >
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>

          {/* 目标 / 冲突 / 钩子 / 回报 */}
          <div className="grid grid-cols-2 gap-2 pt-1">
            <div>
              <span className="text-[10px] text-slate-400">目标</span>
              <input
                value={chapter.goal || ''}
                onChange={(e) => setField('goal', e.target.value)}
                placeholder="本章目标..."
                className="w-full rounded border border-[#d9dfd7] bg-white px-2 py-1 text-[11px] text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors mt-0.5"
              />
            </div>
            <div>
              <span className="text-[10px] text-slate-400">冲突</span>
              <input
                value={chapter.conflict || ''}
                onChange={(e) => setField('conflict', e.target.value)}
                placeholder="本章冲突..."
                className="w-full rounded border border-[#d9dfd7] bg-white px-2 py-1 text-[11px] text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors mt-0.5"
              />
            </div>
            <div>
              <span className="text-[10px] text-slate-400">钩子</span>
              <input
                value={chapter.hook || ''}
                onChange={(e) => setField('hook', e.target.value)}
                placeholder="本章钩子..."
                className="w-full rounded border border-[#d9dfd7] bg-white px-2 py-1 text-[11px] text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors mt-0.5"
              />
            </div>
            <div>
              <span className="text-[10px] text-slate-400">回报</span>
              <input
                value={chapter.payoff || ''}
                onChange={(e) => setField('payoff', e.target.value)}
                placeholder="本章回报..."
                className="w-full rounded border border-[#d9dfd7] bg-white px-2 py-1 text-[11px] text-slate-700 placeholder-slate-400 outline-none focus:border-[#60a5fa] transition-colors mt-0.5"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
