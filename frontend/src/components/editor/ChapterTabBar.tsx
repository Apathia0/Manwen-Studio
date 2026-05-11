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
      <div className="flex items-center h-11 px-4 bg-[#f7f8f5] border-b border-[#d9dfd7]">
        <span className="text-xs text-slate-500">暂无章节</span>
        <button
          onClick={onNewChapter}
          className="ml-auto flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md
                     bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200
                     transition-colors"
        >
          <span className="text-base leading-none">+</span>
          新建章节
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center h-11 bg-[#f7f8f5] border-b border-[#d9dfd7]">
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
                    ? 'text-blue-700 bg-blue-50'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-[#edf1ec]'
                  }
                `}
              >
                <span className={isActive ? 'font-bold' : ''}>第{chapter.chapter_number}话</span>
                {chapter.act && (
                  <span className={`text-[10px] ${isActive ? 'text-blue-500' : 'text-slate-500'}`}>
                    · {chapter.act}
                  </span>
                )}
                {isActive && (
                  <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-blue-500 rounded-full" />
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
                     text-slate-500 hover:text-blue-600 hover:bg-[#f3f5f0]
                     transition-colors"
          title="新建章节"
        >
          <span className="text-lg leading-none">+</span>
        </button>
      </div>
    </div>
  );
}
