import type { AgentMessage, ToolCallInfo } from '@/api/types'

const TOOL_ACTIONS: Record<string, string> = {
  get_chapter_full: '读取章节全文',
  get_all_chapters_summary: '获取章节概览',
  get_framework_detail: '读取故事框架',
  get_story_bible: '读取创作圣经',
  get_scenes: '读取分镜脚本',
  get_character_profiles: '读取角色外貌卡',
  update_chapter_content: '保存章节内容',
  batch_update_chapters: '批量更新章节',
  adjust_chapter_by_instruction: '按指令调整章节',
  rewrite_text_segment: '替换指定段落',
  update_story_info: '更新故事信息',
  update_story_bible: '更新创作圣经',
  update_characters: '更新角色设定',
  adjust_framework: '调整故事框架',
  apply_framework_ops: '执行框架编辑',
  add_chapter_plan: '添加章节规划',
  bulk_add_chapter_plans: '批量添加章节规划',
  batch_adjust_chapters: '批量调整章节',
  update_scenes: '更新分镜脚本',
  get_video_workflow: '读取视频工作流',
  get_workflow_shots: '读取镜头列表',
  get_shot_detail: '读取镜头详情',
  get_video_assets: '读取视频资产',
  get_screenplay: '读取剧本内容',
  update_shot_prompts: '更新镜头提示词',
  update_shot_fields: '更新镜头字段',
  update_screenplay: '更新剧本内容'
}

type ToolStatus = ToolCallInfo['status']

export function getToolDisplayName(name: string): string {
  return TOOL_ACTIONS[name] || '执行创作操作'
}

export function getToolStatusLabel(name: string, status: ToolStatus): string {
  const action = getToolDisplayName(name)
  if (status === 'running') return `正在${action}…`
  if (status === 'error') return `${action}失败`
  return `已${action}`
}

export function getToolResultStatus(result?: unknown, error?: unknown): ToolStatus {
  if (error) return 'error'

  let payload = result
  if (typeof payload === 'string') {
    const text = payload.trim()
    if (!text.startsWith('{')) return 'success'
    try {
      payload = JSON.parse(text)
    } catch {
      return 'success'
    }
  }

  if (payload && typeof payload === 'object') {
    const source = payload as Record<string, unknown>
    if (source.error || source.errors || source.success === false || source.ok === false) {
      return 'error'
    }
  }

  return 'success'
}

/**
 * 工具返回值可能包含正文、提示词、内部字段或凭证，移动端不展示任何原始载荷。
 */
export function sanitizeToolSummary(name: string, result?: unknown, error?: unknown): string {
  return getToolStatusLabel(name, getToolResultStatus(result, error))
}

export function sanitizeToolCall(raw: unknown, index = 0): ToolCallInfo | null {
  if (!raw || typeof raw !== 'object') return null

  const source = raw as Record<string, unknown>
  const nestedFunction = source.function && typeof source.function === 'object'
    ? source.function as Record<string, unknown>
    : undefined
  const name = String(source.name || source.tool_name || nestedFunction?.name || 'tool')
  const rawStatus = source.status
  const status: ToolStatus = rawStatus === 'running' || rawStatus === 'pending'
    ? 'running'
    : rawStatus === 'error' || rawStatus === 'failed'
      ? 'error'
      : getToolResultStatus(source.result, source.error)

  return {
    id: String(source.id || source.tool_call_id || `${name}-${index}`),
    name,
    args: {},
    status,
    summary: getToolStatusLabel(name, status)
  }
}

export function sanitizeAgentMessages(rawMessages: unknown): AgentMessage[] {
  if (!Array.isArray(rawMessages)) return []

  return rawMessages.map((raw, index) => {
    const source = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    const rawToolCalls = source.toolCalls ?? source.tool_calls
    const toolCalls = Array.isArray(rawToolCalls)
      ? rawToolCalls.map((tool, toolIndex) => sanitizeToolCall(tool, toolIndex))
        .filter((tool): tool is ToolCallInfo => tool !== null)
      : undefined

    return {
      id: String(source.id || `message-${index}`),
      role: source.role === 'user' ? 'user' : 'assistant',
      content: typeof source.content === 'string' ? source.content : '',
      toolCalls: toolCalls && toolCalls.length > 0 ? toolCalls : undefined
    }
  })
}
