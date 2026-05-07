import { useCallback, useEffect, useState } from 'react';
import { type Story, type Chapter } from '../api';
import FrameworkPanel from './FrameworkPanel';
import EditorPanel from './EditorPanel';
import MangaPanel from './MangaPanel';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

export default function WorkspaceLayout({
  story,
  chapters,
  currentChapter,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [selectedText, setSelectedText] = useState('');
  const [chapterContext, setChapterContext] = useState<object | undefined>(undefined);

  useEffect(() => {
    setSelectedText('');
    setChapterContext(undefined);
  }, [currentChapter?.id]);

  const handleChapterSelect = useCallback(
    (chapterNumber: number) => {
      const chapter = chapters.find((c) => c.chapter_number === chapterNumber);
      if (chapter) onChapterChange(chapter);
    },
    [chapters, onChapterChange],
  );

  return (
    <div className="flex flex-1 min-h-0">
      <div className="w-[280px] shrink-0 border-r border-gray-800 overflow-y-auto">
        <FrameworkPanel
          story={story}
          chapters={chapters}
          onChapterSelect={handleChapterSelect}
          onFrameworkUpdate={onContentUpdated}
        />
      </div>

      <div className="flex-1 min-w-0 overflow-hidden">
        <EditorPanel
          story={story}
          chapters={chapters}
          currentChapter={currentChapter}
          onChapterChange={onChapterChange}
          onContentUpdated={onContentUpdated}
          onTextSelected={(text, context) => {
            setSelectedText(text);
            setChapterContext(context);
          }}
        />
      </div>

      <div className="w-[380px] shrink-0 border-l border-gray-800 overflow-y-auto">
        <MangaPanel
          chapter={currentChapter}
          onChapterRefresh={onContentUpdated}
          selectedText={selectedText}
          chapterContext={chapterContext as { characters?: any[] } | undefined}
          onClearSelection={() => {
            setSelectedText('');
            setChapterContext(undefined);
          }}
        />
      </div>
    </div>
  );
}
