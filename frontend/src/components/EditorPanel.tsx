import { useState, useCallback, useEffect } from 'react';
import { Save, SquarePen, X } from 'lucide-react';
import { saveChapterContent, type Chapter, type Story } from '../api';
import ChapterTabBar from './editor/ChapterTabBar';
import FrameworkContextBar from './editor/FrameworkContextBar';
import TextEditor from './editor/TextEditor';
import EditorToolbar from './editor/EditorToolbar';
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
    <div className="flex flex-col h-full bg-gray-950 min-w-0">
      <ChapterTabBar
        chapters={chapters}
        currentChapter={currentChapter}
        onSelect={onChapterChange}
        onNewChapter={handleNewChapter}
      />

      {currentChapter && (
        <FrameworkContextBar chapter={currentChapter} story={story} />
      )}

      {currentChapter && (
        <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-gray-800/80 bg-gray-900/70">
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-300 truncate">
              {currentChapter.title || `第 ${currentChapter.chapter_number} 话`}
            </p>
            <p className="text-[11px] text-gray-600">
              {isEditing ? '手动编辑模式已开启' : '可直接选中文本做 AI 改写或分镜'}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {isEditing ? (
              <>
                <button
                  onClick={handleCancelEditing}
                  disabled={savingDraft}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium
                             bg-gray-800 text-gray-300 border border-gray-700 hover:bg-gray-700
                             disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <X size={13} />
                  取消
                </button>
                <button
                  onClick={() => void handleSaveDraft()}
                  disabled={savingDraft || !draftContent.trim()}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium
                             bg-emerald-600 text-white hover:bg-emerald-500
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
                           bg-amber-600/15 text-amber-300 border border-amber-700/40 hover:bg-amber-600/25 transition-colors"
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
        <EditorToolbar
          chapter={currentChapter}
          story={story}
          selectedText={selectedText}
          selectedRange={selectedRange}
          onContentUpdated={onContentUpdated}
          onScenesRequest={handleScenesRequest}
        />
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
  };
}
