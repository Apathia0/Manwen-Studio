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
            content: '已根据这段故事描述生成初始框架。你可以继续告诉我想修改的方向，比如加强冲突、调整角色关系或重排章节节奏。',
          },
        ]);
      } else {
        const result = await adjustFramework(story.id, nextMessages);
        setChatMessages((prev) => [...prev, { role: 'assistant', content: result.reply }]);
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
      const result = await continueFramework(story.id);
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: result.reply || '已续写后续大纲、章节与可能出现的新角色。' },
      ]);
      await onFrameworkUpdate();
    } catch (err: any) {
      setChatError(err.message || '续写框架失败，请稍后重试。');
    } finally {
      setContinueLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-gray-950">
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-violet-400" />
          <h2 className="text-sm font-semibold text-gray-100 tracking-wide">故事框架</h2>
        </div>
        <button
          onClick={toggleAll}
          className="text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
        >
          {allExpanded ? '全部收起' : '全部展开'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-5 py-4 space-y-3">
          <div className="rounded-xl border border-gray-800 bg-gray-900/50 overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
              <div className="flex items-center gap-2">
                <MessageSquare size={13} className="text-violet-400" />
                <span className="text-xs font-semibold text-gray-300 uppercase tracking-wide">框架 AI 对话</span>
              </div>
              <div className="flex items-center gap-2">
                {hasFrameworkContent(story) && (
                  <button
                    onClick={handleContinueFramework}
                    disabled={continueLoading || chatLoading}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg
                               bg-violet-600/15 text-violet-300 border border-violet-700/40 hover:bg-violet-600/25
                               disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {continueLoading ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                    一键续写
                  </button>
                )}
                <button
                  onClick={() => setChatMessages([])}
                  disabled={chatLoading || continueLoading || chatMessages.length === 0}
                  className="text-[11px] text-gray-500 hover:text-gray-300 disabled:opacity-40 transition-colors"
                >
                  清空对话
                </button>
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto px-3 py-3 space-y-2">
              {chatMessages.length === 0 ? (
                <p className="text-xs text-gray-600 leading-relaxed">
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
                        ? 'bg-violet-600/10 border border-violet-700/30 text-violet-100'
                        : 'bg-gray-800/80 border border-gray-700 text-gray-300'
                    }`}
                  >
                    <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-gray-500">
                      {message.role === 'user' ? '你' : 'AI 编辑'}
                    </div>
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  </div>
                ))
              )}
              {chatLoading && (
                <div className="rounded-lg px-3 py-2 text-xs text-gray-400 border border-gray-800 bg-gray-900">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    AI 正在调整框架…
                  </span>
                </div>
              )}
              {continueLoading && (
                <div className="rounded-lg px-3 py-2 text-xs text-gray-400 border border-gray-800 bg-gray-900">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    AI 正在续写后续大纲与章节…
                  </span>
                </div>
              )}
            </div>
            <div className="border-t border-gray-800 px-3 py-3 space-y-2">
              <textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder={hasFrameworkContent(story) ? '告诉 AI 你希望如何修改故事框架…' : '输入故事描述，生成初始框架…'}
                rows={3}
                className="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200
                           placeholder-gray-600 resize-none outline-none focus:border-violet-500 transition-colors"
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-gray-600">
                  {hasFrameworkContent(story) ? 'AI 会基于当前框架增量修改，并保留可用部分。' : '首次发送会直接生成完整框架。'}
                </span>
                <button
                  onClick={handleFrameworkChat}
                  disabled={chatLoading || continueLoading || !chatInput.trim()}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40
                             disabled:cursor-not-allowed transition-colors"
                >
                  {chatLoading ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
                  {hasFrameworkContent(story) ? '发送建议' : '生成框架'}
                </button>
              </div>
              {chatError && <p className="text-xs text-red-400">{chatError}</p>}
            </div>
          </div>

          <div className="rounded-xl border border-gray-800 bg-gray-900/50 overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
              <div className="flex items-center gap-2">
                <Pencil size={13} className="text-amber-400" />
                <span className="text-xs font-semibold text-gray-300 uppercase tracking-wide">手动编辑框架</span>
              </div>
              <button
                onClick={() => {
                  setManualMode((prev) => !prev);
                  setManualDraft(buildFrameworkDraft(story));
                  setManualError('');
                }}
                className="text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
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
                  className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 font-mono text-xs text-gray-200
                             outline-none focus:border-amber-500 resize-y leading-relaxed"
                />
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-gray-600">支持直接编辑 `description`、`tags`、`characters`、`outline`。</span>
                  <button
                    onClick={handleManualSave}
                    disabled={manualSaving}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                               bg-amber-500 hover:bg-amber-400 text-gray-950 disabled:opacity-40 transition-colors"
                  >
                    {manualSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    保存框架
                  </button>
                </div>
                {manualError && <p className="text-xs text-red-400">{manualError}</p>}
              </div>
            ) : (
              <div className="px-3 py-3">
                <p className="text-xs text-gray-600 leading-relaxed">
                  当 AI 调整还不够精确时，可以直接编辑完整框架 JSON，然后一次性保存回标签、角色和大纲。
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-gray-800">
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
  return Boolean(
    (story.description && story.description.trim()) ||
      (story.tags && Object.values(story.tags).some((value) => String(value || '').trim())) ||
      (story.characters && story.characters.length > 0) ||
      story.outline?.three_acts?.length,
  );
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
    <div className="border-b border-gray-800">
      <button
        onClick={() => toggleSection(sectionKey)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-900/30 transition-colors"
      >
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          {SECTION_LABELS[sectionKey]}
        </span>
        <div className="flex items-center gap-2">
          {generated && (
            <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full">已生成</span>
          )}
          {!generated && typeof count === 'number' && count > 0 && (
            <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full">{count} 话</span>
          )}
          <ChevronDown
            size={14}
            className={`text-gray-600 transition-transform duration-200 ${expanded[sectionKey] ? '' : '-rotate-90'}`}
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
        const title = String(chapter?.title || actual?.title || `第${chapterNumber}话`).trim();
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
      title: chapter.title || `第${chapter.chapter_number}话`,
      status: chapter.status ?? (chapter.novel_content ? 'completed' : 'pending'),
      key_events: Array.isArray(chapter.key_events) ? chapter.key_events.map((item) => String(item)) : undefined,
    });
  });

  return planned.sort((a, b) => a.chapter_number - b.chapter_number);
}
