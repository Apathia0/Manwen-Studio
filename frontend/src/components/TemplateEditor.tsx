import { useEffect, useState } from 'react';
import {
  createPromptTemplate,
  updatePromptTemplate,
  getSystemDefaultPrompts,
  type PromptTemplateItem,
  type SystemDefaultPrompts,
} from '../api';

type PromptType = 'framework' | 'chapter' | 'character' | 'manga_style';

const TAB_LABELS: Record<PromptType, string> = {
  framework: '框架生成',
  chapter: '正文扩写',
  character: '角色生成',
  manga_style: '漫画风格',
};

interface Props {
  template?: PromptTemplateItem | null;
  onSave: () => void;
  onCancel: () => void;
}

export default function TemplateEditor({ template, onSave, onCancel }: Props) {
  const isNew = !template;
  const [name, setName] = useState(template?.name || '');
  const [description, setDescription] = useState(template?.description || '');
  const [category, setCategory] = useState(template?.category || '');
  const [tagsStr, setTagsStr] = useState((template?.tags || []).join(', '));
  const [activeTab, setActiveTab] = useState<PromptType>('framework');
  const [expertMode, setExpertMode] = useState(false);
  const [showSysPrompt, setShowSysPrompt] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 系统默认 prompt（参考用）
  const [sysDefaults, setSysDefaults] = useState<SystemDefaultPrompts | null>(null);

  // 增量修改规则（简单模式）
  const [fwRules, setFwRules] = useState(template?.framework_prompt || '');
  const [chRules, setChRules] = useState(template?.chapter_prompt || '');
  const [charRules, setCharRules] = useState(template?.character_prompt || '');
  const [msRules, setMsRules] = useState(template?.manga_style_prompt || '');

  // 专家模式完整 prompt
  const [fwPrompt, setFwPrompt] = useState(template?.framework_prompt || '');
  const [chPrompt, setChPrompt] = useState(template?.chapter_prompt || '');
  const [charPrompt, setCharPrompt] = useState(template?.character_prompt || '');
  const [msPrompt, setMsPrompt] = useState(template?.manga_style_prompt || '');

  const rulesMap: Record<PromptType, [string, (v: string) => void]> = {
    framework: [fwRules, setFwRules],
    chapter: [chRules, setChRules],
    character: [charRules, setCharRules],
    manga_style: [msRules, setMsRules],
  };
  const promptMap: Record<PromptType, [string, (v: string) => void]> = {
    framework: [fwPrompt, setFwPrompt],
    chapter: [chPrompt, setChPrompt],
    character: [charPrompt, setCharPrompt],
    manga_style: [msPrompt, setMsPrompt],
  };

  const [rules, setRules] = rulesMap[activeTab];
  const [prompt, setPrompt] = promptMap[activeTab];

  useEffect(() => {
    getSystemDefaultPrompts()
      .then(setSysDefaults)
      .catch(() => {});
  }, []);

  // 切换到专家模式时，把当前增量规则作为初始化 prompt
  useEffect(() => {
    if (expertMode) {
      const sysDefault = sysDefaults?.[activeTab] || '';
      const currentRules = rulesMap[activeTab][0];
      const existingPrompt = promptMap[activeTab][0];
      // 如果专家 prompt 为空，用「系统默认 + 增量规则」初始化
      if (!existingPrompt.trim()) {
        const built = currentRules.trim()
          ? sysDefault + '\n\n## 用户自定义要求\n' + currentRules.trim()
          : sysDefault;
        promptMap[activeTab][1](built);
      }
    }
  }, [expertMode, activeTab]);

  const currentSysDefault = sysDefaults?.[activeTab] || '';

  async function handleSave() {
    if (!name.trim()) { setError('请输入模板名称'); return; }
    setSaving(true);
    setError(null);
    try {
      const payload: any = {
        name: name.trim(),
        description: description.trim(),
        category: category.trim(),
        tags: tagsStr.split(',').map(t => t.trim()).filter(Boolean),
      };

      if (expertMode) {
        // 专家模式：直接保存完整 prompt
        payload.framework_prompt = fwPrompt.trim() || null;
        payload.chapter_prompt = chPrompt.trim() || null;
        payload.character_prompt = charPrompt.trim() || null;
        payload.manga_style_prompt = msPrompt.trim() || null;
      } else {
        // 简单模式：保存增量规则
        // 如果有增量规则，拼接「系统 prompt + 规则」作为实际使用的完整 prompt
        if (fwRules.trim()) {
          payload.framework_prompt = currentSysDefault + '\n\n## 用户自定义要求\n' + fwRules.trim();
        }
        if (chRules.trim()) {
          payload.chapter_prompt = (sysDefaults?.chapter || '') + '\n\n## 用户自定义要求\n' + chRules.trim();
        }
        if (charRules.trim()) {
          payload.character_prompt = (sysDefaults?.character || '') + '\n\n## 用户自定义要求\n' + charRules.trim();
        }
        if (msRules.trim()) {
          payload.manga_style_prompt = (sysDefaults?.manga_style || '') + '\n\n## 用户自定义要求\n' + msRules.trim();
        }
      }

      if (isNew) {
        await createPromptTemplate(payload);
      } else {
        await updatePromptTemplate(template!.id, payload);
      }
      onSave();
    } catch (e: any) {
      setError(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold text-slate-800">{isNew ? '创建模板' : '编辑模板'}</h2>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{error}</div>
      )}

      {/* 基本信息 */}
      <div className="space-y-2">
        <input
          value={name}
          onChange={e => { setName(e.target.value); setError(null); }}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-2.5 text-sm outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
          placeholder="模板名称（必填）"
        />
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-2.5 text-sm outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
          placeholder="模板描述（方便自己和其他用户理解这个模板的用途）"
          rows={1}
        />
        <div className="flex gap-2">
          <input
            value={category}
            onChange={e => setCategory(e.target.value)}
            className="flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-2.5 text-sm outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
            placeholder="分类（如：玄幻、都市）"
          />
          <input
            value={tagsStr}
            onChange={e => setTagsStr(e.target.value)}
            className="flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-2.5 text-sm outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
            placeholder="标签（逗号分隔）"
          />
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 border-b border-[#e8edf2]">
        {(Object.keys(TAB_LABELS) as PromptType[]).map(tab => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`rounded-t-lg px-3 py-2 text-xs font-medium transition ${
              activeTab === tab ? 'border-b-2 border-[#2563eb] text-[#2563eb]' : 'text-slate-400 hover:text-slate-600'
            }`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* 模式切换 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-400">编辑模式：</span>
        <button
          type="button"
          onClick={() => setExpertMode(false)}
          className={`rounded-xl px-3 py-1.5 text-xs font-medium transition ${
            !expertMode ? 'bg-[#2563eb] text-white' : 'border border-[#d7e3f4] bg-white text-slate-600'
          }`}
        >增量修改</button>
        <button
          type="button"
          onClick={() => setExpertMode(true)}
          className={`rounded-xl px-3 py-1.5 text-xs font-medium transition ${
            expertMode ? 'bg-[#2563eb] text-white' : 'border border-[#d7e3f4] bg-white text-slate-600'
          }`}
        >专家模式</button>
      </div>

      {/* 系统默认 Prompt 参考 */}
      <div>
        <button
          type="button"
          onClick={() => setShowSysPrompt(!showSysPrompt)}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600"
        >
          <span>{showSysPrompt ? '▾' : '▸'}</span>
          {showSysPrompt ? '收起' : '查看'}系统内置提示词（参考）
        </button>
        {showSysPrompt && (
          <div className="mt-2 rounded-2xl border border-[#e8edf2] bg-slate-50 p-3">
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-500 max-h-60 overflow-y-auto">
              {currentSysDefault || '加载中...'}
            </pre>
          </div>
        )}
      </div>

      {/* 编辑区 */}
      <div>
        {expertMode ? (
          /* 专家模式：直接编辑完整 prompt */
          <div className="space-y-1">
            <p className="text-xs text-slate-400">直接修改完整的系统提示词，替换默认行为：</p>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              className="w-full min-h-[300px] rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 font-mono text-xs leading-relaxed outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
              placeholder="在此编辑完整的提示词..."
            />
          </div>
        ) : (
          /* 简单模式：增量修改 */
          <div className="space-y-2">
            <p className="text-xs text-slate-400">
              在系统内置提示词基础上，添加你的自定义要求。AI 生成时会同时遵循系统规则和你的增量指令。
            </p>
            <p className="text-xs text-slate-300">
              提示：可以写「禁止...」「必须...」「强调...」「风格要求...」「不允许出现...」等
            </p>
            <textarea
              value={rules}
              onChange={e => setRules(e.target.value)}
              className="w-full min-h-[160px] rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm leading-relaxed outline-none focus:border-[#93c5fd] focus:ring-2 focus:ring-[#dbeafe]"
              placeholder={
                activeTab === 'framework'
                  ? '例如：\n- 禁止在前5章内揭露世界观核心秘密\n- 每个主要角色必须有独立的成长副线\n- 章节末尾必须留下悬念或钩子\n- 不允许出现穿越/重生等元素'
                  : activeTab === 'chapter'
                  ? '例如：\n- 每章不低于2000字\n- 对话占正文比例不超过40%\n- 场景切换必须有过渡段落\n- 禁止大段内心独白'
                  : activeTab === 'character'
                  ? '例如：\n- 所有角色必须有具体的身高和体型描述\n- 禁止出现玛丽苏/龙傲天类型角色\n- 反派必须有合理的动机而非纯粹邪恶'
                  : '例如：\n- 禁止使用Q版/简笔画风格\n- 场景必须使用电影级构图\n- 角色服装必须符合故事时代背景\n- 画面整体偏向暗色调'
              }
            />
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="flex justify-end gap-2 border-t border-[#e8edf2] pt-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-[#d7e3f4] bg-white px-4 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
        >取消</button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="rounded-xl bg-[#2563eb] px-5 py-2 text-xs font-medium text-white shadow-[0_4px_10px_rgba(37,99,235,0.18)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? '保存中...' : '保存模板'}
        </button>
      </div>
    </div>
  );
}
