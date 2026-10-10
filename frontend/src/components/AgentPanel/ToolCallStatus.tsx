import type { ToolCallInfo } from './AgentPanel';
import { isDisplayableSummary } from '../../lib/agentToolSummary';
import { CANVAS_STAGE_LABELS } from './canvasAgentMode';

const 工具标签映射: Record<string, string> = {
  // ── 小说读取工具 ──
  get_chapter_full: '正在读取章节全文…',
  get_all_chapters_summary: '正在获取章节概览…',
  get_framework_detail: '正在读取故事框架…',
  get_story_bible: '正在读取创作圣经…',
  get_scenes: '正在读取分镜脚本…',
  get_character_profiles: '正在读取角色外貌卡…',
  // ── 小说写入工具 ──
  update_chapter_content: '正在保存章节内容…',
  batch_update_chapters: '正在批量更新章节…',
  adjust_chapter_by_instruction: '正在按指令调整章节…',
  rewrite_text_segment: '正在替换指定段落…',
  update_story_info: '正在更新故事信息…',
  update_story_bible: '正在更新创作圣经…',
  update_characters: '正在更新角色设定…',
  adjust_framework: '正在调整故事框架…',
  apply_framework_ops: '正在执行框架编辑…',
  add_chapter_plan: '正在添加章节规划…',
  bulk_add_chapter_plans: '正在批量添加章节规划…',
  batch_adjust_chapters: '正在批量调整章节…',
  update_scenes: '正在更新分镜脚本…',
  get_manga_storyboard: '正在读取漫画分镜…',
  get_manga_asset_prompts: '正在读取漫画资产提示词…',
  update_manga_storyboard_scene: '正在修改单格分镜…',
  batch_update_manga_storyboard_scenes: '正在批量修改漫画分镜…',
  replace_manga_storyboard: '正在替换完整漫画分镜…',
  update_manga_asset_prompts: '正在更新漫画资产提示词…',
  create_manga_asset: '正在新增漫画资产…',
  // ── 视频读取工具 ──
  get_video_workflow: '正在读取视频工作流…',
  get_workflow_shots: '正在读取镜头列表…',
  get_shot_detail: '正在读取镜头详情…',
  get_video_assets: '正在读取视频资产…',
  get_screenplay: '正在读取剧本内容…',
  // ── 视频写入工具 ──
  update_shot_prompts: '正在更新镜头提示词…',
  update_shot_fields: '正在更新镜头字段…',
  update_screenplay: '正在更新剧本内容…',
  create_video_asset: '正在新增视频资产…',
  update_video_asset_prompts: '正在更新视频资产提示词…',
  // ── 画布工具 ──
  get_canvas_outline: '正在查看画布大纲…',
  search_canvas_nodes: '正在查找画布节点…',
  get_canvas_nodes: '正在读取节点内容…',
  get_canvas_graph: '正在读取画布…',
  get_canvas_status: '正在查看画布进度…',
  get_canvas_node_catalog: '正在读取节点类型…',
  inspect_canvas_media: '正在查看生成的画面…',
  list_canvas_sources: '正在读取可用素材来源…',
  resolve_canvas_source: '正在读取素材来源…',
  draft_screenplay: '正在整理剧本…',
  create_canvas_plan: '正在制定创作计划…',
  get_canvas_plans: '正在读取创作计划…',
  update_canvas_plan: '正在更新创作计划…',
  apply_canvas_ops: '正在修改画布…',
  add_canvas_assets: '正在补建资产…',
  run_canvas_pipeline: '正在启动自动编排…',
};

/** 画布阶段工具按 stage 显示具体动作（编写剧本 / 导演编排 / 生成分镜图片…） */
function 工具标签(call: ToolCallInfo): string {
  if (call.name === 'canvas_stage') {
    const stage = String((call.args as { stage?: unknown } | undefined)?.stage || '');
    return CANVAS_STAGE_LABELS[stage] ? `正在${CANVAS_STAGE_LABELS[stage]}…` : '正在推进制作阶段…';
  }
  return 工具标签映射[call.name] || `正在处理 ${call.name}…`;
}

interface 工具状态属性 {
  toolCalls: ToolCallInfo[];
}

export default function ToolCallStatus({ toolCalls }: 工具状态属性) {
  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <div className="mt-2 space-y-1">
      {toolCalls.map((call) => {
        const 中文标签 = 工具标签(call);
        // 摘要必须是一句话；JSON、多行、超长文本一律不展示（防止把工具原始返回刷到聊天里）
        const 摘要 = isDisplayableSummary(call.summary) ? call.summary.trim() : '';
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
                <span className="text-gray-500">{摘要 || 中文标签.replace('正在', '已').replace('…', '')}</span>
              </>
            )}
            {call.status === 'error' && (
              <>
                <span className="text-red-500 shrink-0">✕</span>
                <span className="text-red-500" title={call.summary}>{摘要 || (call.summary ? `${call.summary.replace(/\s+/g, ' ').slice(0, 80)}…` : '执行失败')}</span>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
