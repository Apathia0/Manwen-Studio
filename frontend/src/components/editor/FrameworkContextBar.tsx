import { type Chapter, type Story } from '../../api';

interface Props {
  chapter: Chapter;
  story: Story;
}

export default function FrameworkContextBar({ chapter, story }: Props) {
  const hasFramework = chapter.act || (chapter.key_events && chapter.key_events.length > 0);
  const storyCharacters = story.characters?.filter((c) => c.name).slice(0, 6) ?? [];

  if (!hasFramework && storyCharacters.length === 0) {
    return (
      <div className="flex items-center h-8 px-4 bg-[#f3f5f0] border-b border-[#d9dfd7]">
        <span className="text-[11px] text-slate-500">暂无大纲约束</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 h-8 px-4 bg-[#f3f5f0] border-b border-[#d9dfd7] overflow-x-auto scrollbar-none">
      {chapter.act && (
        <span className="flex items-center gap-1 text-[11px] text-blue-700 font-medium whitespace-nowrap shrink-0">
          <span className="text-blue-500">•</span>
          大纲约束：{chapter.act}
        </span>
      )}

      {chapter.key_events && chapter.key_events.length > 0 && (
        <div className="flex items-center gap-1.5">
          {chapter.key_events.slice(0, 4).map((event, idx) => {
            const label = typeof event === 'string' ? event : event.title || event.event || `关键事件 ${idx + 1}`;
            return (
              <span
                key={idx}
                className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200 whitespace-nowrap"
              >
                {label}
              </span>
            );
          })}
          {chapter.key_events.length > 4 && (
            <span className="text-[10px] text-slate-500 whitespace-nowrap">+{chapter.key_events.length - 4}项</span>
          )}
        </div>
      )}

      {storyCharacters.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-500 shrink-0">角色：</span>
          {storyCharacters.map((char, idx) => (
            <span key={idx} className="text-[10px] text-slate-600 whitespace-nowrap">
              {char.name}
              {idx < storyCharacters.length - 1 ? '、' : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
