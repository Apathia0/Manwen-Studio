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
      <div className="flex items-center h-8 px-4 bg-gray-800/30 border-b border-gray-800/60">
        <span className="text-[11px] text-gray-600">无大纲约束</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 h-8 px-4 bg-gray-800/30 border-b border-gray-800/60 overflow-x-auto scrollbar-none">
      {chapter.act && (
        <span className="flex items-center gap-1 text-[11px] text-amber-500 font-medium whitespace-nowrap shrink-0">
          <span className="text-amber-600">📍</span>
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
                className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400/80 border border-amber-500/20 whitespace-nowrap"
              >
                {label}
              </span>
            );
          })}
          {chapter.key_events.length > 4 && (
            <span className="text-[10px] text-gray-600 whitespace-nowrap">+{chapter.key_events.length - 4}项</span>
          )}
        </div>
      )}

      {storyCharacters.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-600 shrink-0">角色：</span>
          {storyCharacters.map((char, idx) => (
            <span key={idx} className="text-[10px] text-gray-400 whitespace-nowrap">
              {char.name}{idx < storyCharacters.length - 1 ? '、' : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
