import type { ToolCallInfo } from './AgentPanel';

const 工具标签映射: Record<string, string> = {
  get_chapter_full: '正在读取章节全文…',
  get_all_chapters_summary: '正在获取章节概览…',
  get_framework_detail: '正在读取故事框架…',
  update_chapter_content: '正在保存章节内容…',
  adjust_chapter_by_instruction: '正在按指令调整章节…',
  rewrite_text_segment: '正在替换指定段落…',
  update_story_info: '正在更新故事信息…',
  update_characters: '正在更新角色设定…',
  adjust_framework: '正在调整故事框架…',
  add_chapter_plan: '正在添加章节规划…',
  update_scenes: '正在更新分镜脚本…',
  get_scenes: '正在读取分镜脚本…',
  get_character_profiles: '正在读取角色外貌卡…',
  get_story_bible: '正在读取创作圣经…',
};

interface 工具状态属性 {
  toolCalls: ToolCallInfo[];
}

export default function ToolCallStatus({ toolCalls }: 工具状态属性) {
  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <div className="mt-2 space-y-1">
      {toolCalls.map((call) => {
        const 中文标签 = 工具标签映射[call.name] || `正在执行 ${call.name}…`;
        return (
          <div
            key={call.id}
            className="flex items-center gap-2 text-xs text-gray-500"
          >
            {call.status === 'running' && (
              <>
                <svg className="w-3.5 h-3.5 animate-spin text-blue-500 shrink-0" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>{中文标签}</span>
              </>
            )}
            {call.status === 'success' && (
              <>
                <span className="text-emerald-500 shrink-0">✓</span>
                <span className="text-gray-500">{call.summary || 中文标签.replace('正在', '已').replace('…', '')}</span>
                {call.name === 'adjust_framework' && (
                  <span className="text-gray-400 ml-1">（已自动备份，可在左侧「历史版本」中回滚）</span>
                )}
              </>
            )}
            {call.status === 'error' && (
              <>
                <span className="text-red-500 shrink-0">✕</span>
                <span className="text-red-500">{call.summary || '执行失败'}</span>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
