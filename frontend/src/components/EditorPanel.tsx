import { useState, useCallback, useEffect, useRef } from 'react';
import { Loader2, Save, Send, Sparkles, SquarePen, X } from 'lucide-react';
import { adjustChapterContent, saveChapterContent, type Chapter, type Story } from '../api';
import ChapterTabBar from './editor/ChapterTabBar';
import FrameworkContextBar from './editor/FrameworkContextBar';
import TextEditor from './editor/TextEditor';
import EditorToolbar from './editor/EditorToolbar';
import ContinuitySummaryCard from './ContinuitySummaryCard';
import type { TextSelection } from './editor/TextEditor';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
  onTextSelected: (text: string, chapterContext: object) => void;
}

export default function EditorPanel({
  story,
  chapters,
  currentChapter,
  onChapterChange,
  onContentUpdated,
  onTextSelected,
}: Props) {
  const [selectedText, setSelectedText] = useState('');
  const [selectedRange, setSelectedRange] = useState<{ start: number; end: number } | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [draftContent, setDraftContent] = useState('');
  const [savingDraft, setSavingDraft] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantStatus, setAssistantStatus] = useState('');
  const [assistantError, setAssistantError] = useState('');
  const assistantInputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setIsEditing(false);
    setDraftContent(currentChapter?.novel_content ?? '');
    setSelectedText('');
    setSelectedRange(null);
    setAssistantInput('');
    setAssistantStatus('');
    setAssistantError('');
  }, [currentChapter?.id, currentChapter?.novel_content]);

  const handleTextSelect = useCallback((selection: TextSelection | null) => {
    setSelectedText(selection?.text.trim() ?? '');
    setSelectedRange(selection ? { start: selection.start, end: selection.end } : null);
  }, []);

  const handleNewChapter = useCallback(() => {
    if (chapters.length > 0) {
      onChapterChange(chapters[chapters.length - 1]);
    }
  }, [chapters, onChapterChange]);

  const handleEditorTextSelect = useCallback(
    (selection: TextSelection | null) => {
      handleTextSelect(selection);
      if (currentChapter && selection?.text.trim()) {
        const chapterContext = buildChapterContext(story, currentChapter);
        onTextSelected(selection.text.trim(), chapterContext);
      }
    },
    [currentChapter, story, handleTextSelect, onTextSelected],
  );

  const handleScenesRequest = useCallback(
    (text: string) => {
      setSelectedText(text);
      if (currentChapter) {
        const chapterContext = buildChapterContext(story, currentChapter);
        onTextSelected(text, chapterContext);
      }
    },
    [currentChapter, story, onTextSelected],
  );

  const handleStartEditing = useCallback(() => {
    setDraftContent(currentChapter?.novel_content ?? '');
    setIsEditing(true);
  }, [currentChapter?.novel_content]);

  const handleCancelEditing = useCallback(() => {
    setDraftContent(currentChapter?.novel_content ?? '');
    setIsEditing(false);
  }, [currentChapter?.novel_content]);

  const handleSaveDraft = useCallback(async () => {
    if (!currentChapter || savingDraft) return;
    setSavingDraft(true);
    try {
      await saveChapterContent(currentChapter.id, draftContent);
      setIsEditing(false);
      await onContentUpdated();
    } finally {
      setSavingDraft(false);
    }
  }, [currentChapter, draftContent, onContentUpdated, savingDraft]);

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  };

  const handleAssistantSubmit = useCallback(async () => {
    if (!currentChapter || !assistantInput.trim() || assistantLoading || isEditing) return;
    if (!currentChapter.novel_content?.trim()) {
      setAssistantError('当前章节还没有正文，请先点击“AI 生成本章”或手动输入内容。');
      return;
    }
    setAssistantLoading(true);
    setAssistantError('');
    setAssistantStatus('');
    try {
      await adjustChapterContent(currentChapter.id, assistantInput.trim());
      setAssistantInput('');
      if (assistantInputRef.current) assistantInputRef.current.style.height = 'auto';
      setAssistantStatus('AI 已根据你的建议更新本章正文。');
      await onContentUpdated();
    } catch (err: any) {
      setAssistantError(err.message || 'AI 调整失败。');
    } finally {
      setAssistantLoading(false);
    }
  }, [assistantInput, assistantLoading, currentChapter, isEditing, onContentUpdated]);

  const handleAssistantKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        void handleAssistantSubmit();
      }
    },
    [handleAssistantSubmit],
  );

  return (
    <div className="flex flex-col h-full bg-[#fcfcfa] min-w-0">
      <ChapterTabBar
        chapters={chapters}
        currentChapter={currentChapter}
        onSelect={onChapterChange}
        onNewChapter={handleNewChapter}
      />

      {currentChapter && <FrameworkContextBar chapter={currentChapter} story={story} />}

      {currentChapter && (
        <div className="px-4 py-2 border-b border-[#d7e3f4] bg-[#f8fbff]">
          <ContinuitySummaryCard
            key={currentChapter.id}
            story={story}
            chapter={currentChapter}
            previousChapter={chapters.find((item) => item.chapter_number === currentChapter.chapter_number - 1) ?? null}
            onSaved={onContentUpdated}
          />
        </div>
      )}

      {currentChapter && (
        <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-[#d9dfd7] bg-[#f7f8f5]">
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-700 truncate">
              {currentChapter.title || `第 ${currentChapter.chapter_number} 话`}
            </p>
            <p className="text-[11px] text-slate-500">
              {isEditing ? '手动编辑模式已开启' : '上方阅读正文，下方给 AI 下指令直接改稿'}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {isEditing ? (
              <>
                <button
                  onClick={handleCancelEditing}
                  disabled={savingDraft}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium
                             bg-[#f3f5f0] text-slate-700 border border-[#d9dfd7] hover:bg-[#e8ece6]
                             disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <X size={13} />
                  取消
                </button>
                <button
                  onClick={() => void handleSaveDraft()}
                  disabled={savingDraft || !draftContent.trim()}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium
                             bg-blue-600 text-white hover:bg-blue-500
                             disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Save size={13} />
                  保存正文
                </button>
              </>
            ) : (
              <button
                onClick={handleStartEditing}
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium
                           bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 transition-colors"
              >
                <SquarePen size={13} />
                手动编辑
              </button>
            )}
          </div>
        </div>
      )}

      <TextEditor
        content={currentChapter?.novel_content ?? null}
        draftContent={draftContent}
        editing={isEditing}
        saving={savingDraft}
        onDraftChange={setDraftContent}
        onTextSelect={handleEditorTextSelect}
      />

      {currentChapter && (
        <>
          <div className="border-t border-[#d9dfd7] bg-[#f7f8f5] px-4 py-3">
            <div className="flex items-end gap-2 rounded-xl border border-[#d9dfd7] bg-[#fcfcfa] px-3 py-2 focus-within:border-[#3b82f6] transition-colors">
              <textarea
                ref={assistantInputRef}
                value={assistantInput}
                onChange={(e) => {
                  setAssistantInput(e.target.value);
                  autoResize(e.target);
                  if (assistantError) setAssistantError('');
                  if (assistantStatus) setAssistantStatus('');
                }}
                onKeyDown={handleAssistantKeyDown}
                placeholder="告诉 AI 怎么调整本章，比如：把这一段压缩得更紧张、补一段两人的正面对话..."
                disabled={assistantLoading || isEditing}
                rows={1}
                className="flex-1 bg-transparent text-sm text-slate-800 placeholder-gray-600 resize-none outline-none disabled:opacity-50"
                style={{ maxHeight: '120px', overflow: 'auto' }}
              />
              <button
                onClick={() => void handleAssistantSubmit()}
                disabled={!assistantInput.trim() || assistantLoading || isEditing}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[#2563eb] hover:bg-[#1d4ed8]
                           text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
                title="发送修改建议"
              >
                {assistantLoading ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between gap-3">
              <span className="text-[11px] text-slate-500 inline-flex items-center gap-1.5">
                <Sparkles size={11} className="text-[#2563eb]" />
                AI 会直接改写整章正文，不展示中间对话记录。
              </span>
              {assistantStatus && <span className="text-[11px] text-blue-600">{assistantStatus}</span>}
            </div>
            {assistantError && <p className="mt-2 text-xs text-red-400">{assistantError}</p>}
          </div>

          <EditorToolbar
            chapter={currentChapter}
            story={story}
            selectedText={selectedText}
            selectedRange={selectedRange}
            onContentUpdated={onContentUpdated}
            onScenesRequest={handleScenesRequest}
          />
        </>
      )}
    </div>
  );
}

function buildChapterContext(story: Story, chapter: Chapter): object {
  return {
    act: chapter.act ?? null,
    key_events: chapter.key_events ?? [],
    characters: story.characters?.filter((c) => c.name).map((c) => c.name) ?? [],
    chapter_number: chapter.chapter_number,
    chapter_id: chapter.id,
    chapter_memory: chapter.memory_summary ?? null,
    story_memory: story.story_memory ?? null,
    previous_chapter_number: chapter.chapter_number > 1 ? chapter.chapter_number - 1 : null,
  };
}
