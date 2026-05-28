import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, Loader2, MessageSquare, Pencil, Save, Sparkles, Wand2 } from 'lucide-react';
import {
  adjustFramework,
  continueFramework,
  generateFramework,
  regenerateOutline,
  saveOutlineChapterPlan,
  updateStory,
  type Chapter,
  type FrameworkChatMessage,
  type OutlineChapterPlanInput,
  type Story,
} from '../api';
import type { FrameworkChapter } from './framework/types';
import ChapterListSection from './framework/ChapterListSection';
import CharacterSection from './framework/CharacterSection';
import OutlineSection from './framework/OutlineSection';
import TagSection from './framework/TagSection';

interface Props {
  story: Story;
  chapters: Chapter[];
  onChapterSelect: (chapterNumber: number) => void;
  onFrameworkUpdate: () => void | Promise<void>;
}

type SectionKey = 'tags' | 'characters' | 'outline' | 'chapters';

const SECTION_LABELS: Record<SectionKey, string> = {
  tags: '标签设定',
  characters: '角色设定',
  outline: '故事大纲',
  chapters: '章节列表',
};

export default function FrameworkPanel({ story, chapters, onChapterSelect, onFrameworkUpdate }: Props) {
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [continueLoading, setContinueLoading] = useState(false);
  const [chatError, setChatError] = useState('');
  const [chatMessages, setChatMessages] = useState<FrameworkChatMessage[]>([]);
  const [manualMode, setManualMode] = useState(false);
  const [manualDraft, setManualDraft] = useState('');
  const [manualSaving, setManualSaving] = useState(false);
  const [manualError, setManualError] = useState('');
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    tags: true,
    characters: true,
    outline: true,
    chapters: true,
  });

  useEffect(() => {
    setChatMessages([]);
    setChatInput('');
    setChatError('');
    setManualMode(false);
    setManualError('');
    setManualDraft(buildFrameworkDraft(story));
  }, [story.id]);

  useEffect(() => {
    if (!manualMode) {
      setManualDraft(buildFrameworkDraft(story));
    }
  }, [manualMode, story.description, story.tags, story.characters, story.outline]);

  const frameworkChapters = useMemo(() => buildFrameworkChapters(story, chapters), [story, chapters]);

  const toggleSection = (key: SectionKey) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const allExpanded = Object.values(expanded).every(Boolean);
  const toggleAll = () => {
    const next = !allExpanded;
    setExpanded({ tags: next, characters: next, outline: next, chapters: next });
  };

  const handleFrameworkChat = async () => {
    const instruction = chatInput.trim();
    if (!instruction) return;
    const nextMessages: FrameworkChatMessage[] = [...chatMessages, { role: 'user', content: instruction }];
    setChatMessages(nextMessages);
    setChatInput('');
    setChatLoading(true);
    setChatError('');
    try {
      if (!hasFrameworkContent(story) && chatMessages.length === 0) {
        await generateFramework(story.id, instruction);
        setChatMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: '已根据这段故事描述生成初始框架。你可以继续告诉我想修改的方向，比如加强冲突、调整角色关系或重新编排章节节奏。',
          },
        ]);
      } else {
        const result = await adjustFramework(story.id, nextMessages);
        const operationHint = formatAppliedOperations(result.applied_operations);
        const appliedHint = result.applied_operations?.length
          ? `\n\n实际已应用改动：\n- ${result.applied_operations.join('\n- ')}`
          : '';
        const warningHint = result.warnings?.length
          ? `\n\n未执行或需注意：\n- ${result.warnings.join('\n- ')}`
          : '';
        const validationHint = result.validation_errors?.length
          ? `\n\n校验提示：\n- ${result.validation_errors.join('\n- ')}`
          : '';
        setChatMessages((prev) => [...prev, { role: 'assistant', content: `${result.reply}${operationHint}${appliedHint}${warningHint}${validationHint}` }]);
      }
      await onFrameworkUpdate();
    } catch (err: any) {
      setChatMessages((prev) => prev.slice(0, -1));
      setChatInput(instruction);
      setChatError(err.message || '框架生成失败，请稍后重试。');
    } finally {
      setChatLoading(false);
    }
  };

  const handleManualSave = async () => {
    setManualSaving(true);
    setManualError('');
    try {
      const payload = parseFrameworkDraft(manualDraft);
      await updateStory(story.id, payload);
      await onFrameworkUpdate();
      setManualMode(false);
    } catch (err: any) {
      setManualError(err.message || '保存框架失败。');
    } finally {
      setManualSaving(false);
    }
  };

  const handleContinueFramework = async () => {
    if (!hasFrameworkContent(story) || continueLoading || chatLoading) return;
    setContinueLoading(true);
    setChatError('');
    try {
      const beforeCount = countOutlineChapters(story.outline);
      const result = await continueFramework(story.id);
      const afterCount = countOutlineChapters(result.story?.outline);
      const delta = Math.max(0, afterCount - beforeCount);
      const visibilityHint = afterCount > beforeCount
        ? `\n\n已从 ${beforeCount} 章扩展到 ${afterCount} 章，新增 ${delta} 章。请在下方“故事大纲/章节列表”里查看新增规划。`
        : '\n\n已完成续写请求，但章节数量没有增加；建议查看“故事大纲”是否更新了阶段内容，或输入更明确的扩展章数再试。';
      const operationHint = formatAppliedOperations(result.applied_operations);
      const appliedHint = result.applied_operations?.length
        ? `\n\n实际已应用改动：\n- ${result.applied_operations.join('\n- ')}`
        : '';
      const warningHint = result.warnings?.length
        ? `\n\n未执行或需注意：\n- ${result.warnings.join('\n- ')}`
        : '';
      const validationHint = result.validation_errors?.length
        ? `\n\n校验提示：\n- ${result.validation_errors.join('\n- ')}`
        : '';
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `${result.reply || '已续写后续大纲、章节与可能出现的新角色。'}${visibilityHint}${operationHint}${appliedHint}${warningHint}${validationHint}` },
      ]);
      await onFrameworkUpdate();
    } catch (err: any) {
      setChatError(err.message || '续写框架失败，请稍后重试。');
    } finally {
      setContinueLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#fcfcfa]">
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#d9dfd7] shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-[#2563eb]" />
          <h2 className="text-sm font-semibold text-slate-900 tracking-wide">故事框架</h2>
        </div>
        <button onClick={toggleAll} className="text-[11px] text-slate-500 hover:text-slate-700 transition-colors">
          {allExpanded ? '全部收起' : '全部展开'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-5 py-4 space-y-3">
          <div className="rounded-xl border border-[#d9dfd7] bg-white overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[#d9dfd7]">
              <div className="flex items-center gap-2">
                <MessageSquare size={13} className="text-[#2563eb]" />
                <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">框架 AI 对话</span>
              </div>
              <div className="flex items-center gap-2">
                {hasFrameworkContent(story) && (
                  <button
                    onClick={handleContinueFramework}
                    disabled={continueLoading || chatLoading}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg
                               bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100
                               disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {continueLoading ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                    一键续写
                  </button>
                )}
                <button
                  onClick={() => setChatMessages([])}
                  disabled={chatLoading || continueLoading || chatMessages.length === 0}
                  className="text-[11px] text-slate-500 hover:text-slate-700 disabled:opacity-40 transition-colors"
                >
                  清空对话
                </button>
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto px-3 py-3 space-y-2">
              {chatMessages.length === 0 ? (
                <p className="text-xs text-slate-500 leading-relaxed">
                  {hasFrameworkContent(story)
                    ? '你可以直接告诉 AI 你想怎么改，比如“把主线从复仇改成调查真相”、“强化女主和导师的冲突”、“把第二幕节奏压缩到 6 章”。'
                    : '直接输入故事描述，AI 会先生成初始框架；生成后你还可以继续和它讨论修改方向。'}
                </p>
              ) : (
                chatMessages.map((message, idx) => (
                  <div
                    key={`${message.role}-${idx}`}
                    className={`rounded-lg px-3 py-2 text-xs leading-relaxed ${
                      message.role === 'user'
                        ? 'bg-blue-50 border border-blue-200 text-blue-700'
                        : 'bg-[#f3f5f0]/80 border border-[#d9dfd7] text-slate-700'
                    }`}
                  >
                    <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                      {message.role === 'user' ? '你' : 'AI 编辑'}
                    </div>
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  </div>
                ))
              )}
              {chatLoading && (
                <div className="rounded-lg px-3 py-2 text-xs text-slate-600 border border-[#d9dfd7] bg-white">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    AI 正在调整框架...
                  </span>
                </div>
              )}
              {continueLoading && (
                <div className="rounded-lg px-3 py-2 text-xs text-slate-600 border border-[#d9dfd7] bg-white">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    AI 正在续写后续大纲与章节...
                  </span>
                </div>
              )}
            </div>
            <div className="border-t border-[#d9dfd7] px-3 py-3 space-y-2">
              <textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder={hasFrameworkContent(story) ? '告诉 AI 你希望如何修改故事框架...' : '输入故事描述，生成初始框架...'}
                rows={3}
                className="w-full bg-[#fcfcfa] border border-[#d9dfd7] rounded-lg px-3 py-2 text-sm text-slate-800
                           placeholder-gray-600 resize-none outline-none focus:border-[#3b82f6] transition-colors"
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-slate-500">
                  {hasFrameworkContent(story) ? 'AI 会基于当前框架增量修改，并保留可用部分。' : '首次发送会直接生成完整框架。'}
                </span>
                <button
                  onClick={handleFrameworkChat}
                  disabled={chatLoading || continueLoading || !chatInput.trim()}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-[#2563eb] hover:bg-[#1d4ed8] text-white disabled:opacity-40
                             disabled:cursor-not-allowed transition-colors"
                >
                  {chatLoading ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
                  {hasFrameworkContent(story) ? '发送建议' : '生成框架'}
                </button>
              </div>
              {chatError && <p className="text-xs text-red-500">{chatError}</p>}
            </div>
          </div>

          <div className="rounded-xl border border-[#d9dfd7] bg-white overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[#d9dfd7]">
              <div className="flex items-center gap-2">
                <Pencil size={13} className="text-blue-500" />
                <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">手动编辑框架</span>
              </div>
              <button
                onClick={() => {
                  setManualMode((prev) => !prev);
                  setManualDraft(buildFrameworkDraft(story));
                  setManualError('');
                }}
                className="text-[11px] text-slate-500 hover:text-slate-700 transition-colors"
              >
                {manualMode ? '收起编辑器' : '打开编辑器'}
              </button>
            </div>
            {manualMode ? (
              <div className="px-3 py-3 space-y-2">
                <textarea
                  value={manualDraft}
                  onChange={(e) => setManualDraft(e.target.value)}
                  rows={18}
                  spellCheck={false}
                  className="w-full rounded-lg border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 font-mono text-xs text-slate-800
                             outline-none focus:border-blue-400 resize-y leading-relaxed"
                />
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-slate-500">支持直接编辑 `description`、`tags`、`characters`、`outline`。</span>
                  <button
                    onClick={handleManualSave}
                    disabled={manualSaving}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                               bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 transition-colors"
                  >
                    {manualSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    保存框架
                  </button>
                </div>
                {manualError && <p className="text-xs text-red-500">{manualError}</p>}
              </div>
            ) : (
              <div className="px-3 py-3">
                <p className="text-xs text-slate-500 leading-relaxed">
                  当 AI 调整还不够精确时，可以直接编辑完整框架 JSON，然后一次性保存回标签、角色和大纲。
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-[#d9dfd7]">
          <SectionShell
            sectionKey="tags"
            expanded={expanded}
            toggleSection={toggleSection}
            generated={!!(story.tags && Object.values(story.tags).some(Boolean))}
          >
            <TagSection tags={story.tags ?? null} storyId={story.id} onUpdate={onFrameworkUpdate} />
          </SectionShell>

          <SectionShell
            sectionKey="characters"
            expanded={expanded}
            toggleSection={toggleSection}
            generated={!!(story.characters && story.characters.length > 0)}
          >
            <CharacterSection
              characters={story.characters ?? null}
              storyId={story.id}
              onUpdate={onFrameworkUpdate}
            />
          </SectionShell>

          <SectionShell
            sectionKey="outline"
            expanded={expanded}
            toggleSection={toggleSection}
            generated={!!story.outline?.three_acts?.length}
          >
            <OutlineSection
              outline={story.outline ?? null}
              chapters={chapters}
              storyId={story.id}
              onChapterSelect={onChapterSelect}
              onUpdate={onFrameworkUpdate}
            />
          </SectionShell>

          <SectionShell
            sectionKey="chapters"
            expanded={expanded}
            toggleSection={toggleSection}
            count={frameworkChapters.length}
          >
            <ChapterListSection
              chapters={frameworkChapters}
              actualChapters={chapters}
              storyId={story.id}
              onChapterSelect={onChapterSelect}
              onUpdate={onFrameworkUpdate}
              onGenerateChapters={async () => {
                await regenerateOutline(story.id);
                await onFrameworkUpdate();
              }}
              onSaveChapterPlan={async (mode, chapter, targetChapterNumber) => {
                const payload: OutlineChapterPlanInput = {
                  title: chapter.title,
                  summary: chapter.summary,
                  key_events: chapter.key_events,
                  act: chapter.act,
                  goal: chapter.goal,
                  conflict: chapter.conflict,
                  hook: chapter.hook,
                  payoff: chapter.payoff,
                  highlight: chapter.highlight,
                };
                if (mode === 'append') {
                  await saveOutlineChapterPlan(story.id, { mode, chapter: payload });
                } else if (mode === 'insert_after') {
                  if (typeof targetChapterNumber !== 'number') {
                    throw new Error('Missing insert position');
                  }
                  await saveOutlineChapterPlan(story.id, {
                    mode,
                    after_chapter_number: targetChapterNumber,
                    chapter: payload,
                  });
                } else {
                  if (typeof targetChapterNumber !== 'number') {
                    throw new Error('Missing chapter target');
                  }
                  await saveOutlineChapterPlan(story.id, {
                    mode,
                    target_chapter_number: targetChapterNumber,
                    chapter: payload,
                  });
                }
                await onFrameworkUpdate();
              }}
            />
          </SectionShell>
        </div>

        <div className="h-4" />
      </div>
    </div>
  );
}

function buildFrameworkDraft(story: Story): string {
  return JSON.stringify(
    {
      description: story.description || '',
      tags: story.tags ?? {},
      characters: story.characters ?? [],
      outline: story.outline ?? {},
    },
    null,
    2,
  );
}

function parseFrameworkDraft(raw: string): {
  description?: string;
  tags?: Record<string, unknown>;
  characters?: Record<string, unknown>[];
  outline?: Record<string, unknown>;
} {
  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('框架 JSON 格式不正确，请先修正后再保存。');
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('框架内容必须是一个 JSON 对象。');
  }

  const payload: {
    description?: string;
    tags?: Record<string, unknown>;
    characters?: Record<string, unknown>[];
    outline?: Record<string, unknown>;
  } = {};

  if ('description' in parsed) {
    if (parsed.description !== undefined && typeof parsed.description !== 'string') {
      throw new Error('description 必须是字符串。');
    }
    payload.description = parsed.description ?? '';
  }

  if ('tags' in parsed) {
    if (parsed.tags !== undefined && (typeof parsed.tags !== 'object' || parsed.tags === null || Array.isArray(parsed.tags))) {
      throw new Error('tags 必须是对象。');
    }
    payload.tags = parsed.tags ?? {};
  }

  if ('characters' in parsed) {
    if (parsed.characters !== undefined && !Array.isArray(parsed.characters)) {
      throw new Error('characters 必须是数组。');
    }
    payload.characters = parsed.characters ?? [];
  }

  if ('outline' in parsed) {
    if (parsed.outline !== undefined && (typeof parsed.outline !== 'object' || parsed.outline === null || Array.isArray(parsed.outline))) {
      throw new Error('outline 必须是对象。');
    }
    payload.outline = parsed.outline ?? {};
  }

  return payload;
}

function hasFrameworkContent(story: Story): boolean {
  const acts = Array.isArray(story.outline?.three_acts) ? story.outline?.three_acts : [];
  const hasPlannedChapters = acts.some(
    (act: any) => Array.isArray(act?.chapters) && act.chapters.some((chapter: any) => Number(chapter?.chapter_number) > 0),
  );
  return Boolean(
    acts.length >= 2 && hasPlannedChapters,
  );
}

function countOutlineChapters(outline: Story['outline'] | undefined): number {
  const acts = Array.isArray(outline?.three_acts) ? outline?.three_acts : [];
  const numbers = new Set<number>();
  acts.forEach((act: any) => {
    const actChapters = Array.isArray(act?.chapters) ? act.chapters : [];
    actChapters.forEach((chapter: any) => {
      const chapterNumber = Number(chapter?.chapter_number);
      if (Number.isInteger(chapterNumber) && chapterNumber > 0) {
        numbers.add(chapterNumber);
      }
    });
  });
  return numbers.size;
}

function formatAppliedOperations(ops: string[] | undefined): string {
  if (!ops?.length) return '';
  const opLabels: Record<string, string> = {
    update_character: '更新角色',
    add_character: '新增角色',
    remove_character: '删除角色',
    update_chapter: '更新章节',
    add_chapter: '新增章节',
    insert_chapter_after: '新增章节',
    delete_chapter: '删除章节',
    update_story_description: '更新故事描述',
    update_tags: '更新标签',
    update_act_summary: '更新阶段概述',
  };
  const fieldLabels: Record<string, string> = {
    'patch:description': '故事描述',
    'patch:tags.type': '类型标签',
    'patch:tags.theme': '主题标签',
    'patch:tags.style': '风格标签',
    'patch:tags.audience': '受众标签',
    'patch:outline.themes': '主题列表',
    'patch:outline.foreshadowing': '伏笔列表',
    'patch:outline.serial_strategy': '连载策略',
  };
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const op of ops) {
    const [prefix] = op.split(':');
    const label = fieldLabels[op] || opLabels[prefix];
    if (label && !seen.has(label)) {
      seen.add(label);
      labels.push(label);
    }
    if (labels.length >= 4) break;
  }
  return labels.length ? `\n\n已修改：${labels.join('、')}。` : '';
}

function SectionShell({
  sectionKey,
  expanded,
  toggleSection,
  children,
  generated,
  count,
}: {
  sectionKey: SectionKey;
  expanded: Record<SectionKey, boolean>;
  toggleSection: (key: SectionKey) => void;
  children: ReactNode;
  generated?: boolean;
  count?: number;
}) {
  return (
    <div className="border-b border-[#d9dfd7]">
      <button
        onClick={() => toggleSection(sectionKey)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-[#f3f5f0] transition-colors"
      >
        <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
          {SECTION_LABELS[sectionKey]}
        </span>
        <div className="flex items-center gap-2">
          {generated && (
            <span className="text-[10px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded-full">已生成</span>
          )}
          {!generated && typeof count === 'number' && count > 0 && (
            <span className="text-[10px] text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded-full">{count} 话</span>
          )}
          <ChevronDown
            size={14}
            className={`text-slate-500 transition-transform duration-200 ${expanded[sectionKey] ? '' : '-rotate-90'}`}
          />
        </div>
      </button>
      {expanded[sectionKey] && <div className="px-5 pb-4">{children}</div>}
    </div>
  );
}

function buildFrameworkChapters(story: Story, chapters: Chapter[]): FrameworkChapter[] {
  const actualByNumber = new Map(chapters.map((chapter) => [chapter.chapter_number, chapter]));
  const planned: FrameworkChapter[] = [];
  const acts = story.outline?.three_acts;

  if (Array.isArray(acts)) {
    acts.forEach((act, actIndex) => {
      const actLabel = String((act as any)?.act ?? actIndex + 1);
      const actChapters = Array.isArray((act as any)?.chapters) ? (act as any).chapters : [];
      actChapters.forEach((chapter: any) => {
        const chapterNumber = Number(chapter?.chapter_number);
        if (!Number.isInteger(chapterNumber) || chapterNumber < 1) return;
        const actual = actualByNumber.get(chapterNumber);
        const title = String(chapter?.title || actual?.title || `第 ${chapterNumber} 话`).trim();
        const rawEvents = Array.isArray(chapter?.key_events) ? chapter.key_events : actual?.key_events;
        const keyEvents = Array.isArray(rawEvents)
          ? rawEvents.map((item) => String(item)).filter(Boolean)
          : undefined;
        planned.push({
          id: actual?.id,
          act: actLabel,
          chapter_number: chapterNumber,
          title,
          summary: typeof chapter?.summary === 'string' ? chapter.summary : undefined,
          status: actual?.status ?? (actual?.novel_content ? 'completed' : 'pending'),
          key_events: keyEvents,
          goal: typeof chapter?.goal === 'string' ? chapter.goal : undefined,
          conflict: typeof chapter?.conflict === 'string' ? chapter.conflict : undefined,
          hook: typeof chapter?.hook === 'string' ? chapter.hook : undefined,
          payoff: typeof chapter?.payoff === 'string' ? chapter.payoff : undefined,
          highlight: typeof chapter?.highlight === 'string' ? chapter.highlight : undefined,
        });
      });
    });
  }

  const knownNumbers = new Set(planned.map((item) => item.chapter_number));
  chapters.forEach((chapter) => {
    if (knownNumbers.has(chapter.chapter_number)) return;
    planned.push({
      id: chapter.id,
      act: chapter.act || '',
      chapter_number: chapter.chapter_number,
      title: chapter.title || `第 ${chapter.chapter_number} 话`,
      status: chapter.status ?? (chapter.novel_content ? 'completed' : 'pending'),
      key_events: Array.isArray(chapter.key_events) ? chapter.key_events.map((item) => String(item)) : undefined,
    });
  });

  return planned.sort((a, b) => a.chapter_number - b.chapter_number);
}
