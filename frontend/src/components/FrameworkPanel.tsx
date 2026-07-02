import { memo, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, Edit3, Loader2, MessageSquare, Sparkles, Wand2 } from 'lucide-react';
import {
  adjustFramework,
  continueFramework,
  generateFramework,
  listFrameworkSnapshots,
  regenerateOutline,
  restoreFrameworkSnapshot,
  saveOutlineChapterPlan,
  type Chapter,
  type FrameworkChatMessage,
  type FrameworkSnapshotItem,
  type OutlineChapterPlanInput,
  type Story,
} from '../api';
import type { FrameworkChapter } from './framework/types';
import { toast } from '../lib/toast';
import { confirm } from '../lib/confirm';
import ChapterListSection from './framework/ChapterListSection';
import CharacterSection from './framework/CharacterSection';
import OutlineSection from './framework/OutlineSection';
import TagSection from './framework/TagSection';
import FrameworkEditorModal from './FrameworkEditorModal';

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

export default memo(function FrameworkPanel({ story, chapters, onChapterSelect, onFrameworkUpdate }: Props) {
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [continueLoading, setContinueLoading] = useState(false);
  const [chatError, setChatError] = useState('');
  const [chatMessages, setChatMessages] = useState<FrameworkChatMessage[]>([]);
  const [showEditor, setShowEditor] = useState(false);
  const [frameworkEditMode, setFrameworkEditMode] = useState<'incremental' | 'replace' | 'analyze'>('incremental');
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    tags: true,
    characters: true,
    outline: true,
    chapters: true,
  });
  const [showSnapshotList, setShowSnapshotList] = useState(false);
  const [snapshots, setSnapshots] = useState<FrameworkSnapshotItem[]>([]);
  const [snapshotLoading, setSnapshotLoading] = useState(false);

  useEffect(() => {
    setChatMessages([]);
    setChatInput('');
    setChatError('');
    setShowEditor(false);
  }, [story.id]);

  const frameworkChapters = useMemo(() => buildFrameworkChapters(story, chapters), [story, chapters]);

  const toggleSection = (key: SectionKey) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const allExpanded = Object.values(expanded).every(Boolean);
  const toggleAll = () => {
    const next = !allExpanded;
    setExpanded({ tags: next, characters: next, outline: next, chapters: next });
  };

  const loadSnapshots = useCallback(async () => {
    if (!story.id) return;
    setSnapshotLoading(true);
    try {
      const res = await listFrameworkSnapshots(story.id);
      setSnapshots(res.snapshots);
    } catch {
      setSnapshots([]);
    } finally {
      setSnapshotLoading(false);
    }
  }, [story.id]);

  const handleRestoreSnapshot = useCallback(async (snapshotId: number) => {
    if (!story.id) return;
    if (!await confirm({ message: '回滚将先保存当前状态再恢复所选版本，确认继续？' })) return;
    try {
      await restoreFrameworkSnapshot(story.id, snapshotId);
      window.location.reload();
    } catch (e) {
      toast.error(`回滚失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [story.id]);

  const handleFrameworkChat = async () => {
    const instruction = chatInput.trim();
    if (!instruction) return;
    const modePrefix = frameworkEditMode === 'replace'
      ? '【替换重构模式：允许替换相关范围，不要只追加】\n'
      : frameworkEditMode === 'analyze'
        ? '【仅分析模式：只提出建议，不要修改】\n'
        : '【增量调整模式：优先保留现有内容，只做必要增量修改】\n';
    const fullInstruction = modePrefix + instruction;
    const nextMessages: FrameworkChatMessage[] = [...chatMessages, { role: 'user', content: fullInstruction }];
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
    <>
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
                <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">框架 </span>
              </div>
              <div className="flex items-center gap-2">
                {false && hasFrameworkContent(story) && (
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
                  onClick={() => { setShowSnapshotList(v => !v); if (!showSnapshotList) loadSnapshots(); }}
                  className="text-[11px] text-slate-500 hover:text-slate-700 transition-colors"
                >
                  历史版本
                </button>
                <button
                  onClick={() => setChatMessages([])}
                  disabled={chatLoading || continueLoading || chatMessages.length === 0}
                  className="text-[11px] text-slate-500 hover:text-slate-700 disabled:opacity-40 transition-colors hidden"
                >
                  清空对话
                </button>
              </div>
            </div>

            {showSnapshotList && (
              <div className="border-b border-[#d9dfd7] bg-gray-50 max-h-60 overflow-y-auto">
                <div className="px-3 py-2 text-xs text-gray-500 font-medium flex items-center justify-between">
                  <span>版本历史</span>
                  <button onClick={loadSnapshots} className="text-blue-500 hover:text-blue-700">刷新</button>
                </div>
                <p className="px-3 pb-2 text-[11px] text-gray-400 leading-relaxed">
                  每次调整框架时自动生成新版本，点击回滚可恢复到任意历史版本。
                </p>
                {snapshotLoading ? (
                  <div className="px-3 py-4 text-center text-sm text-gray-400">加载中...</div>
                ) : snapshots.length === 0 ? (
                  <div className="px-3 py-4 text-center text-sm text-gray-400">暂无历史版本</div>
                ) : (
                  <ul>
                    {snapshots.map((snap, idx) => {
                      const time = (() => {
                        try {
                          const d = new Date(snap.created_at);
                          const m = String(d.getMonth() + 1).padStart(2, '0');
                          const day = String(d.getDate()).padStart(2, '0');
                          const h = String(d.getHours()).padStart(2, '0');
                          const min = String(d.getMinutes()).padStart(2, '0');
                          return `${m}/${day} ${h}:${min}`;
                        } catch { return snap.created_at; }
                      })();
                      const sourceLabel: Record<string, string> = {
                        initial_generate: '初始版本',
                        panel_adjust: '框架对话',
                        agent_adjust: 'AI 助手',
                        auto_before_restore: '回滚前自动保存',
                      };
                      return (
                        <li key={snap.id} className="px-3 py-2 border-t border-[#d9dfd7] flex items-center justify-between text-xs">
                          <div className="flex-1 min-w-0">
                            <span className="text-gray-400 mr-1">#{idx + 1}</span>
                            <span>{time}</span>
                            {snap.reply_summary && <span className="text-gray-500 ml-1">- {snap.reply_summary}</span>}
                            <div className="text-gray-400">{sourceLabel[snap.source] || snap.source}</div>
                          </div>
                          <button
                            onClick={() => handleRestoreSnapshot(snap.id)}
                            className="ml-2 px-2 py-0.5 text-xs rounded bg-blue-500 text-white hover:bg-blue-600 flex-shrink-0"
                          >
                            回滚到此
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}

            <div className="max-h-64 overflow-y-auto px-3 py-3 space-y-2 hidden">
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
            <div className="border-t border-[#d9dfd7] px-3 py-3 space-y-2 hidden">
              <div className="flex items-center gap-1">
                {(['incremental', 'replace', 'analyze'] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setFrameworkEditMode(mode)}
                    className={`px-2 py-0.5 text-[10px] rounded-md ${
                      frameworkEditMode === mode
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                    }`}
                  >
                    {mode === 'incremental' ? '增量' : mode === 'replace' ? '替换' : '分析'}
                  </button>
                ))}
              </div>
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
                <Edit3 size={13} className="text-blue-500" />
                <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">手动编辑框架</span>
              </div>
              <button
                onClick={() => setShowEditor(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                           bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              >
                <Edit3 size={12} />
                打开可视化编辑器
              </button>
            </div>
            <div className="px-3 py-3">
              <p className="text-xs text-slate-500 leading-relaxed">
                使用可视化编辑器直接修改框架的各个模块（描述、标签、角色、大纲），左侧实时预览，右侧按标签页编辑。
              </p>
            </div>
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
                    throw new Error('缺少插入位置');
                  }
                  await saveOutlineChapterPlan(story.id, {
                    mode,
                    after_chapter_number: targetChapterNumber,
                    chapter: payload,
                  });
                } else {
                  if (typeof targetChapterNumber !== 'number') {
                    throw new Error('缺少章节目标');
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
    {showEditor && (
      <FrameworkEditorModal
        story={story}
        onClose={() => setShowEditor(false)}
        onSaved={onFrameworkUpdate}
      />
    )}
  </>
  );
})

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
