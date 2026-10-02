import { useEffect, useMemo, useState } from 'react';
import { Loader2, Save, Sparkles } from 'lucide-react';
import type { CreativeProfile } from '../../api';

interface Props {
  profile: CreativeProfile | null;
  onUpdate: (profile: Partial<CreativeProfile>) => Promise<void>;
}

interface SelectorOption<T extends string> {
  value: T;
  label: string;
  description: string;
}

const PLATFORM_OPTIONS: SelectorOption<string>[] = [
  { value: 'qidian', label: '起点中文网', description: '传统网文，重节奏与爽点' },
  { value: 'zhulang', label: '纵横中文网', description: '偏长篇世界观和多题材' },
  { value: 'qq', label: 'QQ阅读', description: '移动端导向，重追读感' },
  { value: 'fanqie', label: '番茄小说', description: '免费阅读，强开篇和强钩子' },
];

const AUDIENCE_OPTIONS: SelectorOption<string>[] = [
  { value: 'male', label: '男频', description: '升级打怪、热血冒险' },
  { value: 'female', label: '女频', description: '情感细腻、人物关系' },
  { value: 'lightnovel', label: '轻小说', description: '轻松日常、二次元风格' },
];

const MALE_GENRES: SelectorOption<string>[] = [
  { value: 'xuanhuan', label: '玄幻', description: '东方奇幻世界' },
  { value: 'xiuxian', label: '修仙', description: '修炼成长之路' },
  { value: 'dushi', label: '都市', description: '现代都市背景' },
  { value: 'lishi', label: '历史', description: '穿越历史题材' },
  { value: 'kehuan', label: '科幻', description: '未来科技幻想' },
  { value: 'wuxia', label: '武侠', description: '快意恩仇江湖' },
];

const FEMALE_GENRES: SelectorOption<string>[] = [
  { value: 'yanqing', label: '言情', description: '浪漫爱情故事' },
  { value: 'gudai', label: '古代言情', description: '古风背景情感线' },
  { value: 'dushi', label: '都市情感', description: '现代情感纠葛' },
  { value: 'chongsheng', label: '重生', description: '重来一次的人生' },
  { value: 'chuanyue', label: '穿越', description: '时空切换与身份变化' },
];

const LIGHT_NOVEL_GENRES: SelectorOption<string>[] = [
  { value: 'riyong', label: '日常', description: '轻松校园和生活感' },
  { value: 'maoxian', label: '冒险', description: '奇幻世界探索' },
  { value: 'kehuan', label: '科幻', description: '未来设定与想象力' },
  { value: 'xuanhuan', label: '异能', description: '超能力与战斗成长' },
];

const PACE_OPTIONS: SelectorOption<string>[] = [
  { value: 'strong_hook', label: '强钩子', description: '开局快，悬念密' },
  { value: 'steady', label: '稳推进', description: '铺垫充分，节奏稳定' },
  { value: 'warm', label: '慢热型', description: '氛围感强，渐进展开' },
];

const LENGTH_OPTIONS: SelectorOption<string>[] = [
  { value: 'short', label: '短篇 30章', description: '适合试水和练手' },
  { value: 'medium', label: '中篇 100章', description: '标准网文体量' },
  { value: 'long', label: '长篇 300章', description: '适合持续连载' },
  { value: 'extra_long', label: '超长篇 500章+', description: '大世界长线运营' },
];

const GOAL_OPTIONS: SelectorOption<string>[] = [
  { value: 'publish', label: '平台投稿', description: '优先面向可发布性' },
  { value: 'practice', label: '练习创作', description: '优先写作体验和训练' },
  { value: 'series', label: '系列长篇', description: '优先留出后续扩展空间' },
];

const CUSTOM_GENRE_VALUE = '__custom__';

export default function CreativeModePanel({ profile, onUpdate }: Props) {
  const [platformMode, setPlatformMode] = useState(profile?.platform_mode ?? 'qidian');
  const [audienceMode, setAudienceMode] = useState(profile?.audience_mode ?? 'male');
  const [genre, setGenre] = useState(profile?.genre ?? 'xuanhuan');
  const [customGenre, setCustomGenre] = useState(profile?.custom_genre ?? '');
  const [paceMode, setPaceMode] = useState(profile?.pace_mode ?? 'strong_hook');
  const [targetLength, setTargetLength] = useState(profile?.target_length ?? 'medium');
  const [creationGoal, setCreationGoal] = useState(profile?.creation_goal ?? 'publish');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const genreOptions = useMemo<SelectorOption<string>[]>(() => {
    if (audienceMode === 'female') return FEMALE_GENRES;
    if (audienceMode === 'lightnovel') return LIGHT_NOVEL_GENRES;
    return MALE_GENRES;
  }, [audienceMode]);

  const isCustomGenre = genre === CUSTOM_GENRE_VALUE;

  useEffect(() => {
    const allowed = genreOptions.some((option) => option.value === genre);
    if (!allowed && genre !== CUSTOM_GENRE_VALUE) {
      setGenre(genreOptions[0]?.value ?? 'xuanhuan');
    }
  }, [audienceMode, genre, genreOptions]);

  useEffect(() => {
    if (!profile) return;
    setPlatformMode(profile.platform_mode ?? 'qidian');
    setAudienceMode(profile.audience_mode ?? 'male');
    setGenre(profile.custom_genre?.trim() ? CUSTOM_GENRE_VALUE : (profile.genre ?? 'xuanhuan'));
    setCustomGenre(profile.custom_genre ?? '');
    setPaceMode(profile.pace_mode ?? 'strong_hook');
    setTargetLength(profile.target_length ?? 'medium');
    setCreationGoal(profile.creation_goal ?? 'publish');
  }, [profile]);

  async function handleSave() {
    setSaving(true);
    try {
      await onUpdate({
        platform_mode: platformMode,
        audience_mode: audienceMode,
        genre: isCustomGenre ? (customGenre.trim() || '自定义类型') : genre,
        custom_genre: isCustomGenre ? customGenre.trim() : '',
        pace_mode: paceMode,
        target_length: targetLength,
        creation_goal: creationGoal,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex h-full flex-col bg-[#fcfcfa]">
      <div className="shrink-0 border-b border-[#d7e3f4] px-5 py-3">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-[#2563eb]" />
          <h2 className="text-sm font-semibold tracking-wide text-slate-900">创作模式配置</h2>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="space-y-6 px-5 py-4">
          <SelectorGroup title="目标平台" options={PLATFORM_OPTIONS} value={platformMode} onChange={setPlatformMode} />
          <SelectorGroup title="读者受众" options={AUDIENCE_OPTIONS} value={audienceMode} onChange={setAudienceMode} />
          <SelectorGroup
            title="作品类型"
            options={[
              ...genreOptions,
              { value: CUSTOM_GENRE_VALUE, label: '自定义', description: '输入更细分的题材标签' },
            ]}
            value={genre}
            onChange={setGenre}
            cardClassName="min-h-[92px]"
          />

          {isCustomGenre && (
            <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
              <div className="text-sm font-semibold text-slate-800">自定义作品标签</div>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                例如：游戏文、赛博修仙、刑侦言情、克苏鲁校园、经营种田。
              </p>
              <input
                value={customGenre}
                onChange={(e) => setCustomGenre(e.target.value)}
                placeholder="输入你的自定义题材"
                className="mt-3 w-full rounded-xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2.5 text-sm text-slate-800 outline-none transition-colors focus:border-[#93c5fd] focus:bg-white"
              />
            </div>
          )}

          <SelectorGroup title="节奏偏好" options={PACE_OPTIONS} value={paceMode} onChange={setPaceMode} />
          <SelectorGroup title="预计体量" options={LENGTH_OPTIONS} value={targetLength} onChange={setTargetLength} />
          <SelectorGroup title="创作目标" options={GOAL_OPTIONS} value={creationGoal} onChange={setCreationGoal} />
        </div>
      </div>

      <div className="shrink-0 border-t border-[#d7e3f4] px-5 py-3">
        <button
          onClick={() => void handleSave()}
          disabled={saving || (isCustomGenre && !customGenre.trim())}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-[#2563eb] px-4 py-2.5 text-sm font-medium text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)] transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
          {saving ? '保存中...' : saved ? '已保存' : '保存创作画像'}
        </button>
      </div>
    </div>
  );
}

function SelectorGroup<T extends string>({
  title,
  options,
  value,
  onChange,
  cardClassName,
}: {
  title: string;
  options: SelectorOption<T>[];
  value: T;
  onChange: (value: T) => void;
  cardClassName?: string;
}) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-1.5">
        <Sparkles size={13} className="text-[#2563eb]" />
        <span className="text-sm font-semibold text-slate-800">{title}</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {options.map((option) => {
          const selected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={`rounded-2xl border px-4 py-3 text-left transition-all ${
                selected
                  ? 'border-[#2563eb] bg-blue-50 shadow-[0_6px_18px_rgba(37,99,235,0.12)]'
                  : 'border-[#d7e3f4] bg-white hover:border-[#93c5fd] hover:bg-[#fafdff]'
              } ${cardClassName ?? 'min-h-[88px]'}`}
            >
              <div className={`text-base font-semibold ${selected ? 'text-[#1d4ed8]' : 'text-slate-800'}`}>
                {option.label}
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-500">{option.description}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
