import { type Chapter } from '../../api';

interface Props {
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onSelect: (chapter: Chapter) => void;
  onNewChapter: () => void;
}

export default function ChapterTabBar({ chapters, currentChapter, onSelect, onNewChapter }: Props) {
  if (chapters.length === 0) {
    return (
      <div className="flex items-center h-11 px-4 bg-gray-900/80 border-b border-gray-800">
        <span className="text-xs text-gray-600">暂无章节</span>
        <button
          onClick={onNewChapter}
          className="ml-auto flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md
                     bg-amber-600/20 hover:bg-amber-600/30 text-amber-400 border border-amber-700/40
                     transition-colors"
        >
          <span className="text-base leading-none">+</span>
          新建章节
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center h-11 bg-gray-900/80 border-b border-gray-800">
      <div className="flex-1 flex overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-px">
          {chapters.map((chapter) => {
            const isActive = chapter.id === currentChapter?.id;
            return (
              <button
                key={chapter.id}
                onClick={() => onSelect(chapter)}
                className={`
                  relative flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium
                  whitespace-nowrap transition-colors shrink-0
                  ${isActive
                    ? 'text-amber-400 bg-amber-500/10'
                    : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'
                  }
                `}
              >
                <span className={isActive ? 'font-bold' : ''}>
                  第{chapter.chapter_number}话
                </span>
                {chapter.act && (
                  <span className={`text-[10px] ${isActive ? 'text-amber-600' : 'text-gray-600'}`}>
                    · {chapter.act}
                  </span>
                )}
                {isActive && (
                  <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-amber-500 rounded-full" />
                )}
              </button>
            );
          })}
        </div>
      </div>
      <div className="shrink-0 px-2">
        <button
          onClick={onNewChapter}
          className="flex items-center justify-center w-7 h-7 rounded-md
                     text-gray-500 hover:text-amber-400 hover:bg-gray-800
                     transition-colors"
          title="新建章节"
        >
          <span className="text-lg leading-none">+</span>
        </button>
      </div>
    </div>
  );
}
