import { ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import type { Chapter } from '../api';

interface ChapterInfo {
  chapter: Chapter;
  shotCount: number;   // 该章已有分镜数，0 表示未分镜
  hasFrames: boolean;  // 是否已有首尾帧
}

interface ChapterListPanelProps {
  chapters: ChapterInfo[];
  selectedChapterId: number | null;
  collapsed: boolean;
  className?: string;
  onSelect: (chapter: Chapter) => void;
  onToggleCollapse: () => void;
}

/**
 * 视频工作台左侧章节选择面板
 * 信息版：显示章节序号+标题+分镜进度状态
 * 折叠时仅显示展开按钮，释放主工作区空间
 */
export default function ChapterListPanel({
  chapters,
  selectedChapterId,
  collapsed,
  className = '',
  onSelect,
  onToggleCollapse,
}: ChapterListPanelProps) {
  if (collapsed) {
    return (
      <div className={`w-10 shrink-0 flex flex-col items-center pt-4 border-r border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] ${className}`}>
        <button
          onClick={onToggleCollapse}
          className="rounded-lg p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          title="展开章节列表"
        >
          <ChevronRight size={18} />
        </button>
      </div>
    );
  }

  return (
    <div className={`w-[160px] shrink-0 flex flex-col overflow-hidden border-r border-[#d7e3f4] bg-white ${className}`}>
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#e5edf8]">
        <h3 className="text-sm font-semibold text-slate-900">章节选择</h3>
        <button
          onClick={onToggleCollapse}
          className="rounded-lg p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          title="收起章节列表"
        >
          <ChevronLeft size={16} />
        </button>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto py-2">
        {chapters.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-slate-400">
            <FileText size={24} className="mx-auto mb-2 opacity-50" />
            暂无章节
          </div>
        ) : (
          chapters.map((info) => (
            <button
              key={info.chapter.id}
              onClick={() => onSelect(info.chapter)}
              className={`w-full text-left px-4 py-2.5 transition-colors ${
                selectedChapterId === info.chapter.id
                  ? 'bg-blue-50 border-r-2 border-[#2563eb]'
                  : 'hover:bg-slate-50 border-r-2 border-transparent'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={`text-sm font-medium ${
                  selectedChapterId === info.chapter.id ? 'text-[#2563eb]' : 'text-slate-800'
                }`}>
                  第{info.chapter.chapter_number}章
                </span>
                {info.shotCount > 0 && (
                  <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-[10px] text-emerald-600 font-medium">
                    {info.shotCount}镜
                  </span>
                )}
                {info.hasFrames && (
                  <span className="text-[10px] text-emerald-500">✓</span>
                )}
              </div>
              {info.chapter.title && (
                <p className="mt-0.5 text-xs text-slate-500 truncate">{info.chapter.title}</p>
              )}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
