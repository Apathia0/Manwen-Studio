import { useState, useCallback, useEffect } from 'react';
import { Save, SquarePen, X } from 'lucide-react';
import { saveChapterContent, type Chapter, type Story } from '../api';
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

  useEffect(() => {
    setIsEditing(false);
    setDraftContent(currentChapter?.novel_content ?? '');
    setSelectedText('');
    setSelectedRange(null);
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

  return (
    <div className="flex h-full min-w-0 flex-col bg-[#fcfcfa]">
      <ChapterTabBar
        chapters={chapters}
        currentChapter={currentChapter}
        onSelect={onChapterChange}
        onNewChapter={handleNewChapter}
      />

      {currentChapter ? <FrameworkContextBar chapter={currentChapter} story={story} /> : null}

      {currentChapter ? (
        <div className="border-b border-[#d7e3f4] bg-[#f8fbff] px-4 py-2">
          <ContinuitySummaryCard
            key={currentChapter.id}
            story={story}
            chapter={currentChapter}
            previousChapter={chapters.find((item) => item.chapter_number === currentChapter.chapter_number - 1) ?? null}
            onSaved={onContentUpdated}
          />
        </div>
      ) : null}

      {currentChapter ? (
        <div className="flex items-center justify-between gap-3 border-b border-[#d9dfd7] bg-[#f7f8f5] px-4 py-2">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-slate-700">
              {currentChapter.title || `第 ${currentChapter.chapter_number} 话`}
            </p>
            <p className="text-[11px] text-slate-500">
              {isEditing ? '当前为手动编辑模式。' : '章节正文编辑区，AI 对话入口已统一迁移到右侧 AI 助手。'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {isEditing ? (
              <>
                <button
                  onClick={handleCancelEditing}
                  disabled={savingDraft}
                  className="inline-flex items-center gap-1 rounded-md border border-[#d9dfd7] bg-[#f3f5f0] px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-[#e8ece6] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <X size={13} />
                  取消
                </button>
                <button
                  onClick={() => void handleSaveDraft()}
                  disabled={savingDraft || !draftContent.trim()}
                  className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Save size={13} />
                  保存正文
                </button>
              </>
            ) : (
              <button
                onClick={handleStartEditing}
                className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100"
              >
                <SquarePen size={13} />
                手动编辑
              </button>
            )}
          </div>
        </div>
      ) : null}

      <TextEditor
        content={currentChapter?.novel_content ?? null}
        draftContent={draftContent}
        editing={isEditing}
        saving={savingDraft}
        onDraftChange={setDraftContent}
        onTextSelect={handleEditorTextSelect}
      />

      {currentChapter ? (
        <EditorToolbar
          chapter={currentChapter}
          story={story}
          selectedText={selectedText}
          selectedRange={selectedRange}
          onContentUpdated={onContentUpdated}
          onScenesRequest={handleScenesRequest}
        />
      ) : null}
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
