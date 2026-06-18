import { get, post, put, del } from '@/utils/request'
import { uploadFile } from '@/utils/upload'
import type {
  ScriptScene, VideoShot, VideoAsset, VideoGenerationJob,
  StoryVideoCharacter, ChapterVideoWorkflow, ChapterVideoShot,
  VideoModel, ChapterVideoWorkflowStatus, VideoStylePreset,
  ReanalyzeShotPromptsResponse, PreviewVideoPromptResponse,
} from './types'

// ── 剧本 (Screenplay) ──

/** 生成剧本 */
export function generateScreenplay(chapterId: number, payload: {
  mode?: string
  style?: string
  target_duration_seconds?: number
  scene_count_hint?: number
  regenerate?: boolean
}): Promise<{ screenplay: string; scenes: ScriptScene[] }> {
  return post(`/api/video/chapters/${chapterId}/screenplay/generate`, payload)
}

/** 获取剧本场景列表 */
export function listScreenplayScenes(chapterId: number): Promise<{ scenes: ScriptScene[]; screenplay: string }> {
  return get(`/api/video/chapters/${chapterId}/screenplay/scenes`)
}

// ── 镜头 (Shots) ──

/** 生成场景镜头 */
export function generateSceneShots(sceneId: number, payload?: {
  style?: string
  shot_count_hint?: number
  regenerate?: boolean
  duration_budget_seconds?: number
}): Promise<{ scene_id: number; shots: VideoShot[] }> {
  return post(`/api/video/scenes/${sceneId}/shots/generate`, payload)
}

/** 获取场景镜头列表 */
export function listSceneShots(sceneId: number): Promise<{ scene_id: number; shots: VideoShot[] }> {
  return get(`/api/video/scenes/${sceneId}/shots`)
}

/** 更新镜头 */
export function updateVideoShot(shotId: number, payload: Partial<VideoShot>): Promise<VideoShot> {
  return put(`/api/shots/${shotId}`, payload)
}

/** 删除镜头 */
export function deleteShot(shotId: number): Promise<{ ok: boolean; shot_id: number }> {
  return del(`/api/shots/${shotId}`)
}

/** 生成镜头提示词 */
export function generateShotPrompts(shotId: number, payload?: {
  style?: string
  provider?: string
  include_references?: boolean
  instruction?: string
}): Promise<{ shot: VideoShot }> {
  return post(`/api/shots/${shotId}/prompts/generate`, payload)
}

// ── 故事版 (Storyboard) ──

/** 生成章节故事版 */
export function generateChapterStoryboard(chapterId: number, payload?: {
  provider?: string
  style?: string
  style_preset?: string
}): Promise<{ shots: any[] }> {
  return post(`/api/chapters/${chapterId}/storyboard/generate`, payload)
}

// ── 工作流 (Workflow) ──

/** 创建视频工作流 */
export function createChapterVideoWorkflow(payload: {
  chapter_id: number
  character_reference_ids?: number[]
  video_style?: string
  style_reference_image_url?: string | null
}): Promise<ChapterVideoWorkflow> {
  return post('/api/video/chapter-workflows', payload)
}

/** 获取工作流 */
export function getChapterVideoWorkflow(workflowId: number): Promise<ChapterVideoWorkflow> {
  return get(`/api/video/chapter-workflows/${workflowId}`)
}

/** 获取章节的工作流列表 */
export function listChapterVideoWorkflows(chapterId: number): Promise<{ workflows: ChapterVideoWorkflow[]; total: number }> {
  return get(`/api/video/chapter-workflows/by-chapter/${chapterId}`)
}

/** 重新生成工作流故事版 */
export function regenerateChapterWorkflowStoryboard(shotId: number, promptOverride?: string, referenceAssetIds?: number[]): Promise<ChapterVideoShot> {
  return post(`/api/video/chapter-workflows/shots/${shotId}/regenerate-storyboard`, {
    target: 'storyboard',
    prompt_override: promptOverride ?? null,
    reference_asset_ids: referenceAssetIds ?? [],
  })
}

/** 重新生成工作流视频 */
export function regenerateChapterWorkflowVideo(shotId: number, promptOverride?: string, referenceAssetIds?: number[], aspectRatio: '16:9' | '9:16' = '16:9'): Promise<ChapterVideoShot> {
  return post(`/api/video/chapter-workflows/shots/${shotId}/regenerate-video`, {
    target: 'video',
    prompt_override: promptOverride ?? null,
    reference_asset_ids: referenceAssetIds ?? [],
    aspect_ratio: aspectRatio,
  })
}

/** 拼接章节视频 */
export function concatChapterVideoWorkflow(workflowId: number): Promise<{ video_url: string; shot_count: number; duration_seconds: number; message?: string }> {
  return post(`/api/video/chapter-workflows/${workflowId}/concat`)
}

// ── 角色 (Characters) ──

/** 获取视频角色列表 */
export function listStoryVideoCharacters(storyId: number): Promise<{ characters: StoryVideoCharacter[]; video_character_profiles: string }> {
  return get(`/api/stories/${storyId}/video-characters`)
}

/** 生成视频角色 */
export function generateStoryVideoCharacters(storyId: number): Promise<{ characters: StoryVideoCharacter[]; video_character_profiles: string }> {
  return post(`/api/stories/${storyId}/video-characters/generate`)
}

// ── 渲染 (Render) ──

/** 渲染镜头视频 */
export function renderShotVideo(shotId: number, payload: {
  model: string
  prompt?: string
  duration?: number
  size?: string
  orientation?: string
  input_reference?: string
}): Promise<VideoGenerationJob> {
  return post(`/api/shots/${shotId}/render`, payload)
}

/** 获取视频模型列表 */
export function getVideoModels(): Promise<{ models: VideoModel[] }> {
  return get('/api/video/models')
}

/** 获取视频作业状态 */
export function getVideoJob(jobId: number): Promise<VideoGenerationJob> {
  return get(`/api/video/jobs/${jobId}`)
}

/** 同意故事版 */
export function approveShotStoryboard(shotId: number): Promise<{ storyboard_locked: boolean; storyboard_asset_id: number }> {
  return post(`/api/shots/${shotId}/storyboard/approve`)
}

/** 拒绝故事版 */
export function rejectShotStoryboard(shotId: number): Promise<{ storyboard_locked: boolean; storyboard_asset_id: number }> {
  return post(`/api/shots/${shotId}/storyboard/reject`)
}

// ── 工作流阶段 (Workflow Stages) ──

/** 获取工作流状态 */
export function getChapterVideoWorkflowStatus(workflowId: number): Promise<ChapterVideoWorkflowStatus> {
  return get(`/api/video/chapter-workflows/${workflowId}/status`)
}

/** 拆镜（剧本→镜头列表） */
export function parseChapterWorkflowShots(workflowId: number): Promise<Record<string, unknown>> {
  return post(`/api/video/chapter-workflows/${workflowId}/parse`)
}

/** 生成镜头详情 */
export function generateChapterWorkflowShotDetails(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  return post(`/api/video/chapter-workflows/${workflowId}/generate-details`, payload)
}

/** 批量生成故事版 */
export function generateChapterWorkflowStoryboards(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  return post(`/api/video/chapter-workflows/${workflowId}/storyboards`, payload)
}

/** 批量生成视频 */
export function generateChapterWorkflowVideos(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  return post(`/api/video/chapter-workflows/${workflowId}/videos`, payload)
}

/** 全自动执行所有阶段 */
export function runAllChapterWorkflowStages(workflowId: number): Promise<Record<string, unknown>> {
  return post(`/api/video/chapter-workflows/${workflowId}/run-all`)
}

/** 重新分析故事版提示词 */
export function reanalyzeChapterWorkflowStoryboardPrompt(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  return post(`/api/video/chapter-workflows/${workflowId}/storyboards/reanalyze-prompt`, payload)
}

/** 单镜头重新分析提示词 */
export function reanalyzeChapterShotPrompts(shotId: number): Promise<ReanalyzeShotPromptsResponse> {
  return post(`/api/video/chapter-workflows/shots/${shotId}/reanalyze-prompts`)
}

/** 预览视频提示词 */
export function previewVideoPrompt(
  shotId: number,
  referenceAssetIds?: number[],
  promptOverride?: string
): Promise<PreviewVideoPromptResponse> {
  const params: string[] = []
  if (referenceAssetIds && referenceAssetIds.length > 0) {
    params.push(`reference_asset_ids=${referenceAssetIds.join(',')}`)
  }
  if (promptOverride) {
    params.push(`prompt_override=${encodeURIComponent(promptOverride)}`)
  }
  const qs = params.join('&')
  return get(`/api/video/chapter-workflows/shots/${shotId}/preview-video-prompt${qs ? `?${qs}` : ''}`)
}

/** 重置工作流 */
export function resetChapterWorkflow(workflowId: number): Promise<{ ok: boolean; workflow_status: string }> {
  return post(`/api/video/chapter-workflows/${workflowId}/reset`)
}

/** 清除镜头故事版 */
export function clearShotStoryboard(shotId: number): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  return post(`/api/video/chapter-workflows/shots/${shotId}/clear-storyboard`)
}

/** 清除镜头视频 */
export function clearShotVideo(shotId: number): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  return post(`/api/video/chapter-workflows/shots/${shotId}/clear-video`)
}

/** 保存镜头提示词 */
export function saveChapterShotPrompts(
  shotId: number,
  prompts: {
    storyboard_prompt?: string | null
    video_prompt?: string | null
    scene_prompt?: string | null
    prop_prompts?: Array<{ name: string; prompt: string }> | null
  }
): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  return post(`/api/video/chapter-workflows/shots/${shotId}/save-prompts`, prompts)
}

// ── 风格预设 (Style Presets) ──

/** 列出风格预设 */
export function listStylePresets(): Promise<{ presets: VideoStylePreset[] }> {
  return get(`/api/video-style-presets`)
}

/** 获取故事视频风格预设 */
export function getStoryVideoStylePreset(storyId: number): Promise<{ story_id: number; style_preset_id: number | null; style_preset: VideoStylePreset | null }> {
  return get(`/api/video/stories/${storyId}/style-preset`)
}

/** 设置故事视频风格预设 */
export function setStoryVideoStylePreset(storyId: number, stylePresetId: number): Promise<{ story_id: number; style_preset_id: number }> {
  return put(`/api/video/stories/${storyId}/style-preset`, { style_preset_id: stylePresetId })
}

// ── 资产管理 (Asset Management) ──

/** 列出章节视频资产 */
export function listVideoAssets(chapterId: number, assetType?: string): Promise<{ chapter_id: number; assets: VideoAsset[] }> {
  const params = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : ''
  return get(`/api/chapters/${chapterId}/video-assets${params}`)
}

/** 删除视频资产 */
export function deleteVideoAsset(assetId: number): Promise<{ ok: boolean; asset_id: number }> {
  return del(`/api/video-assets/${assetId}`)
}

// ── 上传 (Upload) ──

/** 上传风格参考图 */
export function uploadStyleReferenceImage(
  workflowId: number,
  filePath: string
): Promise<{ success: boolean; style_reference_image_url: string }> {
  return uploadFile(`/api/video/chapter-workflows/${workflowId}/style-reference`, filePath)
}
