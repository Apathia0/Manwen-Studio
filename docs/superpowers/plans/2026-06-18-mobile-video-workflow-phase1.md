# 移动端视频工作流移植 - 阶段一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 web 端新版 Chapter Video Workflow 流水线核心功能移植到移动端，实现工作流创建 → 拆镜 → 生成详情 → 批量故事版 → 批量视频 → 整章拼接的完整流程。

**Architecture:** 多页面分阶段工作台架构。新增 2 个页面（video-workflow.vue 工作流管理 + video-shots.vue 镜头列表）+ 1 个 Pinia store（videoGen）+ 1 个 composable（useWorkflowPolling）+ 扩展现有 videoWorkflow store 和 API 层。在 chapter-view.vue 添加第 5 个标签「视频」作为入口，同时在 workspace/index.vue 添加视频创作快捷入口。

**Tech Stack:** Vue 3.4 + uni-app 3.0 + Pinia 2.1 + TypeScript 5.3 + Sass + vue-tsc

**Spec:** `docs/superpowers/specs/2026-06-18-mobile-video-workflow-migration-design.md`

---

## 文件结构

### 新增文件

| 文件路径 | 职责 |
|---------|------|
| `storycanvas-mobile/src/stores/videoGen.ts` | 生成状态管理 Pinia store（对标 web 端 videoGenStore.ts） |
| `storycanvas-mobile/src/composables/useWorkflowPolling.ts` | 工作流状态轮询 composable |
| `storycanvas-mobile/src/pages/workspace/video-workflow.vue` | 工作流管理页面（创建/列表/状态轮询/风格选择） |
| `storycanvas-mobile/src/pages/workspace/video-shots.vue` | 镜头列表页面（网格+批量操作+拆镜+拼接） |
| `storycanvas-mobile/src/utils/upload.ts` | 文件上传工具（uni.uploadFile 封装） |

### 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `storycanvas-mobile/src/api/types.ts` | 新增 `ChapterVideoWorkflowStatus`、`VideoStylePreset`、`ReanalyzeShotPromptsResponse` 类型 |
| `storycanvas-mobile/src/api/video.ts` | 新增 ~15 个 Phase 1 核心 API 函数 |
| `storycanvas-mobile/src/stores/videoWorkflow.ts` | 扩展状态和方法（parseShots/generateStoryboards/generateVideos/concatVideo/resetWorkflow 等） |
| `storycanvas-mobile/src/pages/workspace/chapter-view.vue` | tabs 从 4 个改为 5 个，插入「视频」标签，原「助手」标签从 #tab-3 移到 #tab-4 |
| `storycanvas-mobile/src/pages/workspace/index.vue` | 添加「视频创作」快捷入口卡片 |
| `storycanvas-mobile/src/pages.json` | 注册 2 个新页面路由 |

---

## Task 1: 类型定义补充

**Files:**
- Modify: `storycanvas-mobile/src/api/types.ts` (末尾追加)

- [ ] **Step 1: 在 types.ts 末尾追加新类型**

在 `storycanvas-mobile/src/api/types.ts` 文件末尾（第 404 行 `export interface VideoModel` 之后）追加以下类型定义：

```typescript
/** 章节视频工作流状态 */
export interface ChapterVideoWorkflowStatus {
  id: number
  chapter_id: number
  workflow_status: string
  total_shots: number
  completed_shots: number
  failed_shots: number
  error_message?: string | null
  task_id?: string | null
  stage?: string | null
  message?: string | null
  retry_count?: number
  max_retries?: number
  next_retry_at?: string | null
}

/** 视频风格预设 */
export interface VideoStylePreset {
  id: number
  name: string
  category: string
  image_url?: string | null
  prompt_template?: string | null
  image_style_params?: Record<string, unknown> | null
  video_style_params?: Record<string, unknown> | null
  sort_order: number
}

/** 重新分析镜头提示词响应 */
export interface ReanalyzeShotPromptsResponse {
  shot_id: number
  storyboard_prompt: string
  video_prompt: string
  character_prompts: Array<{ name: string; prompt: string }>
  scene_prompt?: string
  prop_prompts?: Array<{ name: string; prompt: string }>
}

/** 预览视频提示词响应 */
export interface PreviewVideoPromptResponse {
  assembled_prompt: string
  parts: { part1: string; part2: string; part3: string | null }
}
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS (无新增类型错误)

- [ ] **Step 3: Commit**

```bash
cd storycanvas-mobile
git add src/api/types.ts
git commit -m "feat(mobile): add video workflow type definitions"
```

---

## Task 2: API 函数补全 - 工作流阶段 API

**Files:**
- Modify: `storycanvas-mobile/src/api/video.ts` (在现有函数之后追加)

- [ ] **Step 1: 在 video.ts 末尾追加工作流阶段 API 函数**

在 `storycanvas-mobile/src/api/video.ts` 文件末尾（第 164 行 `rejectShotStoryboard` 函数之后）追加以下 API 函数。首先在文件顶部的 import 语句中添加新类型：

修改第 2-6 行的 import 块，从：
```typescript
import type {
  ScriptScene, VideoShot, VideoAsset, VideoGenerationJob,
  StoryVideoCharacter, ChapterVideoWorkflow, ChapterVideoShot,
  VideoModel,
} from './types'
```
改为：
```typescript
import type {
  ScriptScene, VideoShot, VideoAsset, VideoGenerationJob,
  StoryVideoCharacter, ChapterVideoWorkflow, ChapterVideoShot,
  VideoModel, ChapterVideoWorkflowStatus, VideoStylePreset,
  ReanalyzeShotPromptsResponse, PreviewVideoPromptResponse,
} from './types'
```

然后在文件末尾追加：

```typescript
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
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd storycanvas-mobile
git add src/api/video.ts
git commit -m "feat(mobile): add video workflow stage and style preset APIs"
```

---

## Task 3: 文件上传工具

**Files:**
- Create: `storycanvas-mobile/src/utils/upload.ts`

- [ ] **Step 1: 创建文件上传工具**

创建 `storycanvas-mobile/src/utils/upload.ts`：

```typescript
import { BASE_URL } from './constants'
import { getToken } from './storage'

/**
 * 上传文件到后端（跨平台：H5 / 小程序 / App）
 * 使用 uni.uploadFile 实现 multipart/form-data 上传
 *
 * @param url API 路径（相对路径，如 /api/video/chapter-workflows/1/style-reference）
 * @param filePath 本地文件路径（来自 uni.chooseImage 的 tempFilePaths）
 * @param name 文件字段名（默认 'file'）
 * @param formData 额外的表单字段
 * @returns 解析后的 JSON 响应
 */
export function uploadFile<T = any>(
  url: string,
  filePath: string,
  name: string = 'file',
  formData?: Record<string, string>
): Promise<T> {
  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: fullUrl,
      filePath,
      name,
      formData,
      header: headers,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(res.data) as T)
          } catch {
            reject(new Error('响应解析失败'))
          }
        } else {
          try {
            const data = JSON.parse(res.data)
            reject(new Error(data.detail || data.message || '上传失败'))
          } catch {
            reject(new Error(`上传失败 (${res.statusCode})`))
          }
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '文件上传失败'))
      }
    })
  })
}

/**
 * 选择图片并上传
 *
 * @param count 最多选择图片数量
 * @returns 选中的图片临时路径数组
 */
export function chooseImages(count: number = 1): Promise<string[]> {
  return new Promise((resolve, reject) => {
    uni.chooseImage({
      count,
      success: (res) => {
        resolve(res.tempFilePaths)
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '选择图片失败'))
      }
    })
  })
}
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd storycanvas-mobile
git add src/utils/upload.ts
git commit -m "feat(mobile): add cross-platform file upload utility"
```

---

## Task 4: 上传 API 函数补充

**Files:**
- Modify: `storycanvas-mobile/src/api/video.ts` (末尾追加上传相关 API)

- [ ] **Step 1: 在 video.ts 末尾追加上传风格参考图 API**

在 `storycanvas-mobile/src/api/video.ts` 文件顶部的 import 块中添加 uploadFile 引入。在第 1 行 `import { get, post, put, del } from '@/utils/request'` 之后追加：

```typescript
import { uploadFile } from '@/utils/upload'
```

然后在文件末尾追加：

```typescript
// ── 上传 (Upload) ──

/** 上传风格参考图 */
export function uploadStyleReferenceImage(
  workflowId: number,
  filePath: string
): Promise<{ success: boolean; style_reference_image_url: string }> {
  return uploadFile(`/api/video/chapter-workflows/${workflowId}/style-reference`, filePath)
}
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd storycanvas-mobile
git add src/api/video.ts
git commit -m "feat(mobile): add style reference image upload API"
```

---

## Task 5: videoGen Pinia Store

**Files:**
- Create: `storycanvas-mobile/src/stores/videoGen.ts`

- [ ] **Step 1: 创建 videoGen store**

创建 `storycanvas-mobile/src/stores/videoGen.ts`，对标 web 端 `frontend/src/videoGenStore.ts`，用 Pinia + uni.setStorageSync 实现：

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type AssetType = 'video' | 'storyboard' | 'character' | 'scene'

export interface VideoGenState {
  active: boolean
  jobId: number | null
  status: string
  progress: number
  statusMsg: string
  errorMsg: string
  lastEventAt: number
}

const STORAGE_KEY = 'video_gen_states'
const STATE_EXPIRY_MS = 24 * 60 * 60 * 1000

function stateKey(shotId: number, type: AssetType = 'video'): string {
  return type === 'video' ? String(shotId) : `${shotId}:${type}`
}

function loadPersistedStates(): Map<string, VideoGenState> {
  try {
    const stored = uni.getStorageSync(STORAGE_KEY)
    if (!stored) return new Map()

    const parsed = typeof stored === 'string' ? JSON.parse(stored) : stored
    const now = Date.now()
    const states = new Map<string, VideoGenState>()

    for (const [key, state] of Object.entries(parsed)) {
      if (now - (state as VideoGenState).lastEventAt < STATE_EXPIRY_MS) {
        states.set(key, state as VideoGenState)
      }
    }

    return states
  } catch {
    return new Map()
  }
}

function persistStates(states: Map<string, VideoGenState>): void {
  try {
    const obj: Record<string, VideoGenState> = {}
    states.forEach((state, key) => {
      obj[key] = state
    })
    uni.setStorageSync(STORAGE_KEY, JSON.stringify(obj))
  } catch {
    // 存储可能已满，忽略错误
  }
}

export const useVideoGenStore = defineStore('videoGen', () => {
  const states = ref(loadPersistedStates())

  function persist() {
    persistStates(states.value)
  }

  function get(shotId: number, type: AssetType = 'video'): VideoGenState | undefined {
    return states.value.get(stateKey(shotId, type))
  }

  function set(shotId: number, state: VideoGenState, type: AssetType = 'video') {
    states.value.set(stateKey(shotId, type), { ...state, lastEventAt: Date.now() })
    persist()
  }

  function patch(shotId: number, p: Partial<VideoGenState>, type: AssetType = 'video') {
    const key = stateKey(shotId, type)
    const cur = states.value.get(key)
    if (!cur) return
    states.value.set(key, { ...cur, ...p, lastEventAt: Date.now() })
    persist()
  }

  function startJob(shotId: number, jobId: number, type: AssetType = 'video') {
    const msg = type === 'video' ? '正在提交视频任务...'
      : type === 'storyboard' ? '正在生成故事版...'
      : type === 'character' ? '正在生成角色资产...'
      : '正在生成场景...'
    states.value.set(stateKey(shotId, type), {
      active: true,
      jobId,
      status: 'pending',
      progress: 0,
      statusMsg: msg,
      errorMsg: '',
      lastEventAt: Date.now(),
    })
    persist()
  }

  function updateProgress(shotId: number, status: string, progress: number, statusMsg: string, type: AssetType = 'video') {
    patch(shotId, { status, progress, statusMsg }, type)
  }

  function markSucceeded(shotId: number, type: AssetType = 'video') {
    const msg = type === 'video' ? '视频生成完成'
      : type === 'storyboard' ? '故事版生成完成'
      : type === 'character' ? '角色资产生成完成'
      : '场景生成完成'
    patch(shotId, { active: false, status: 'succeeded', progress: 100, statusMsg: msg }, type)
  }

  function markFailed(shotId: number, errorMsg: string, type: AssetType = 'video') {
    const msg = type === 'video' ? '视频生成失败'
      : type === 'storyboard' ? '故事版生成失败'
      : type === 'character' ? '角色资产生成失败'
      : '场景生成失败'
    patch(shotId, { active: false, status: 'failed', progress: 0, errorMsg, statusMsg: msg }, type)
  }

  function clear(shotId: number, type: AssetType = 'video') {
    if (states.value.delete(stateKey(shotId, type))) {
      persist()
    }
  }

  function clearAll(shotId: number) {
    const prefix = `${shotId}:`
    let changed = false
    for (const key of states.value.keys()) {
      if (key === String(shotId) || key.startsWith(prefix)) {
        states.value.delete(key)
        changed = true
      }
    }
    if (changed) persist()
  }

  function cleanupExpired() {
    const now = Date.now()
    let changed = false
    states.value.forEach((state, key) => {
      if (now - state.lastEventAt > STATE_EXPIRY_MS) {
        states.value.delete(key)
        changed = true
      }
    })
    if (changed) persist()
  }

  return {
    states,
    get,
    set,
    patch,
    startJob,
    updateProgress,
    markSucceeded,
    markFailed,
    clear,
    clearAll,
    cleanupExpired,
  }
})
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/stores/videoGen.ts`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
cd storycanvas-mobile
git add src/stores/videoGen.ts
git commit -m "feat(mobile): add videoGen Pinia store for generation state management"
```

---

## Task 6: 扩展 videoWorkflow Store

**Files:**
- Modify: `storycanvas-mobile/src/stores/videoWorkflow.ts`

- [ ] **Step 1: 扩展 videoWorkflow store 的 import 和状态**

修改 `storycanvas-mobile/src/stores/videoWorkflow.ts`。

将第 1-4 行的 import 块从：
```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { videoApi } from '@/api'
import type { ScriptScene, VideoShot, ChapterVideoWorkflow, StoryVideoCharacter } from '@/api/types'
```
改为：
```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { videoApi } from '@/api'
import type {
  ScriptScene, VideoShot, ChapterVideoWorkflow, StoryVideoCharacter,
  ChapterVideoShot, VideoAsset, VideoStylePreset, ChapterVideoWorkflowStatus,
} from '@/api/types'
```

在 `characterProfiles` ref（第 15 行）之后、`loading` ref（第 16 行）之前追加新状态：

```typescript
  const currentWorkflow = ref<ChapterVideoWorkflow | null>(null)
  const currentShots = ref<ChapterVideoShot[]>([])
  const chapterAssets = ref<VideoAsset[]>([])
  const stylePresets = ref<VideoStylePreset[]>([])
  const selectedReferenceIds = ref<number[]>([])
  const selectedStyle = ref('写实电影感')
  const styleReferenceImageUrl = ref<string | null>(null)
  const videoAspectRatio = ref<'16:9' | '9:16'>('16:9')
  const selectedShotIds = ref<number[]>([])
  const skippedShotIds = ref<number[]>([])
  const workflowRunning = ref(false)
  const concatVideoUrl = ref<string | null>(null)
```

- [ ] **Step 2: 在 store 的 return 语句前追加新方法**

在 `generateCharacters` 函数（约第 146 行）之后、`return` 语句（约第 148 行）之前追加以下方法：

```typescript
  async function loadWorkflowDetail(workflowId: number) {
    loading.value = true
    try {
      const detail = await videoApi.getChapterVideoWorkflow(workflowId)
      currentWorkflow.value = detail
      currentShots.value = detail.shots || []
      return detail
    } catch {
      currentWorkflow.value = null
      currentShots.value = []
      return null
    } finally {
      loading.value = false
    }
  }

  async function loadChapterAssets(chapterId: number) {
    try {
      const res = await videoApi.listVideoAssets(chapterId)
      chapterAssets.value = res.assets || []
    } catch {
      chapterAssets.value = []
    }
  }

  async function loadStylePresets() {
    try {
      const res = await videoApi.listStylePresets()
      stylePresets.value = res.presets || []
    } catch {
      stylePresets.value = []
    }
  }

  async function parseShots(workflowId: number) {
    generating.value = true
    phase.value = 'shots'
    try {
      const result = await videoApi.parseChapterWorkflowShots(workflowId)
      await loadWorkflowDetail(workflowId)
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function generateShotDetails(workflowId: number, shotIds: number[]) {
    generating.value = true
    phase.value = 'shots'
    try {
      const result = await videoApi.generateChapterWorkflowShotDetails(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function generateStoryboards(workflowId: number, shotIds: number[]) {
    generating.value = true
    phase.value = 'storyboard'
    try {
      const result = await videoApi.generateChapterWorkflowStoryboards(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function generateVideos(workflowId: number, shotIds: number[]) {
    generating.value = true
    phase.value = 'video'
    try {
      const result = await videoApi.generateChapterWorkflowVideos(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function runAllStages(workflowId: number) {
    generating.value = true
    try {
      const result = await videoApi.runAllChapterWorkflowStages(workflowId)
      await loadWorkflowDetail(workflowId)
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function reanalyzeStoryboardPrompt(workflowId: number, shotIds: number[]) {
    generating.value = true
    try {
      const result = await videoApi.reanalyzeChapterWorkflowStoryboardPrompt(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
      return result
    } finally {
      generating.value = false
    }
  }

  async function reanalyzeShotPrompts(shotId: number) {
    generating.value = true
    try {
      return await videoApi.reanalyzeChapterShotPrompts(shotId)
    } finally {
      generating.value = false
    }
  }

  async function concatVideo(workflowId: number) {
    generating.value = true
    phase.value = 'concat'
    try {
      const result = await videoApi.concatChapterVideoWorkflow(workflowId)
      concatVideoUrl.value = result.video_url
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function resetWorkflow(workflowId: number) {
    generating.value = true
    try {
      await videoApi.resetChapterWorkflow(workflowId)
      await loadWorkflowDetail(workflowId)
      concatVideoUrl.value = null
      selectedShotIds.value = []
      skippedShotIds.value = []
    } finally {
      generating.value = false
    }
  }

  async function clearShotStoryboard(shotId: number) {
    try {
      await videoApi.clearShotStoryboard(shotId)
      if (currentWorkflow.value) {
        await loadWorkflowDetail(currentWorkflow.value.id)
      }
    } catch (e: any) {
      uni.showToast({ title: e.message || '清除失败', icon: 'none' })
      throw e
    }
  }

  async function clearShotVideo(shotId: number) {
    try {
      await videoApi.clearShotVideo(shotId)
      if (currentWorkflow.value) {
        await loadWorkflowDetail(currentWorkflow.value.id)
      }
    } catch (e: any) {
      uni.showToast({ title: e.message || '清除失败', icon: 'none' })
      throw e
    }
  }

  async function saveShotPrompts(shotId: number, prompts: {
    storyboard_prompt?: string | null
    video_prompt?: string | null
    scene_prompt?: string | null
    prop_prompts?: Array<{ name: string; prompt: string }> | null
  }) {
    try {
      const result = await videoApi.saveChapterShotPrompts(shotId, prompts)
      if (currentWorkflow.value) {
        await loadWorkflowDetail(currentWorkflow.value.id)
      }
      return result
    } catch (e: any) {
      uni.showToast({ title: e.message || '保存失败', icon: 'none' })
      throw e
    }
  }

  async function uploadStyleReferenceImage(workflowId: number, filePath: string) {
    generating.value = true
    try {
      const result = await videoApi.uploadStyleReferenceImage(workflowId, filePath)
      styleReferenceImageUrl.value = result.style_reference_image_url
      return result
    } finally {
      generating.value = false
    }
  }

  function toggleShotSelection(shotId: number) {
    const idx = selectedShotIds.value.indexOf(shotId)
    if (idx >= 0) {
      selectedShotIds.value.splice(idx, 1)
    } else {
      selectedShotIds.value.push(shotId)
    }
  }

  function toggleShotSkip(shotId: number) {
    const idx = skippedShotIds.value.indexOf(shotId)
    if (idx >= 0) {
      skippedShotIds.value.splice(idx, 1)
    } else {
      skippedShotIds.value.push(shotId)
      // 从选中列表中移除
      const selIdx = selectedShotIds.value.indexOf(shotId)
      if (selIdx >= 0) {
        selectedShotIds.value.splice(selIdx, 1)
      }
    }
  }

  function selectAllShots() {
    if (currentShots.value.length === 0) return
    selectedShotIds.value = currentShots.value
      .filter(s => !skippedShotIds.value.includes(s.id))
      .map(s => s.id)
  }

  function clearSelection() {
    selectedShotIds.value = []
  }
```

- [ ] **Step 3: 扩展 return 语句**

将 return 语句从：
```typescript
  return {
    screenplay,
    scenes,
    shots,
    workflows,
    activeWorkflow,
    characterList,
    characterProfiles,
    loading,
    generating,
    phase,
    isBusy,
    sceneOptions,
    fetchScreenplay,
    generateScreenplay,
    fetchShots,
    generateShots,
    fetchWorkflows,
    createWorkflow,
    fetchCharacters,
    generateCharacters,
  }
```
改为：
```typescript
  return {
    screenplay,
    scenes,
    shots,
    workflows,
    activeWorkflow,
    characterList,
    characterProfiles,
    loading,
    generating,
    phase,
    isBusy,
    sceneOptions,
    // 新增状态
    currentWorkflow,
    currentShots,
    chapterAssets,
    stylePresets,
    selectedReferenceIds,
    selectedStyle,
    styleReferenceImageUrl,
    videoAspectRatio,
    selectedShotIds,
    skippedShotIds,
    workflowRunning,
    concatVideoUrl,
    // 原有方法
    fetchScreenplay,
    generateScreenplay,
    fetchShots,
    generateShots,
    fetchWorkflows,
    createWorkflow,
    fetchCharacters,
    generateCharacters,
    // 新增方法
    loadWorkflowDetail,
    loadChapterAssets,
    loadStylePresets,
    parseShots,
    generateShotDetails,
    generateStoryboards,
    generateVideos,
    runAllStages,
    reanalyzeStoryboardPrompt,
    reanalyzeShotPrompts,
    concatVideo,
    resetWorkflow,
    clearShotStoryboard,
    clearShotVideo,
    saveShotPrompts,
    uploadStyleReferenceImage,
    toggleShotSelection,
    toggleShotSkip,
    selectAllShots,
    clearSelection,
  }
```

- [ ] **Step 4: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 5: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/stores/videoWorkflow.ts`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
cd storycanvas-mobile
git add src/stores/videoWorkflow.ts
git commit -m "feat(mobile): extend videoWorkflow store with workflow stage methods"
```

---

## Task 7: useWorkflowPolling Composable

**Files:**
- Create: `storycanvas-mobile/src/composables/useWorkflowPolling.ts`

- [ ] **Step 1: 创建工作流轮询 composable**

创建 `storycanvas-mobile/src/composables/useWorkflowPolling.ts`：

```typescript
import { ref, watch, onUnmounted, type Ref } from 'vue'
import { videoApi } from '@/api'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useVideoGenStore } from '@/stores/videoGen'

const ACTIVE_STATUSES = new Set([
  'parsing_shots',
  'generating_storyboards',
  'generating_videos',
  'reanalyzing_prompts',
  'generating_details',
])

/**
 * 工作流状态轮询 composable
 * 对标 web 端 pollWorkflowUntilSettled
 *
 * @param workflowId 响应式的工作流 ID
 * @returns isPolling - 是否正在轮询；stop - 停止轮询
 */
export function useWorkflowPolling(workflowId: Ref<number | null>) {
  const videoWorkflowStore = useVideoWorkflowStore()
  const videoGenStore = useVideoGenStore()
  const timerRef = ref<ReturnType<typeof setTimeout> | null>(null)
  const isPolling = ref(false)

  async function tick() {
    if (!workflowId.value) return
    isPolling.value = true
    try {
      const status = await videoApi.getChapterVideoWorkflowStatus(workflowId.value)
      const detail = await videoApi.getChapterVideoWorkflow(workflowId.value)
      videoWorkflowStore.currentWorkflow = detail
      videoWorkflowStore.currentShots = detail.shots || []
      videoWorkflowStore.workflowRunning = ACTIVE_STATUSES.has(status.workflow_status)

      if (ACTIVE_STATUSES.has(status.workflow_status)) {
        timerRef.value = setTimeout(() => tick(), 4000)
        return
      }

      // 工作流完成：更新 videoGenStore
      detail.shots.forEach(shot => {
        if (shot.status === 'storyboard_ready') {
          videoGenStore.markSucceeded(shot.id, 'storyboard')
        }
        if (shot.status === 'video_ready') {
          videoGenStore.markSucceeded(shot.id)
        }
        if (shot.status === 'failed') {
          const sbState = videoGenStore.get(shot.id, 'storyboard')
          if (sbState?.active) {
            videoGenStore.markFailed(shot.id, shot.error_message || '故事版生成失败', 'storyboard')
          }
          videoGenStore.markFailed(shot.id, shot.error_message || '视频生成失败')
        }
      })

      // 刷新章节资产
      if (detail.chapter_id) {
        videoWorkflowStore.loadChapterAssets(detail.chapter_id)
      }
    } catch (error: any) {
      console.error('工作流轮询失败:', error)
      videoWorkflowStore.workflowRunning = false
    } finally {
      isPolling.value = false
    }
  }

  function start() {
    stop()
    if (workflowId.value) tick()
  }

  function stop() {
    if (timerRef.value) {
      clearTimeout(timerRef.value)
      timerRef.value = null
    }
    isPolling.value = false
  }

  // 工作流 ID 变化时重新开始轮询
  watch(workflowId, (newId) => {
    if (newId) {
      start()
    } else {
      stop()
    }
  })

  onUnmounted(stop)

  return { isPolling, start, stop }
}
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/composables/useWorkflowPolling.ts`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
cd storycanvas-mobile
git add src/composables/useWorkflowPolling.ts
git commit -m "feat(mobile): add useWorkflowPolling composable"
```

---

## Task 8: pages.json 注册新页面

**Files:**
- Modify: `storycanvas-mobile/src/pages.json`

- [ ] **Step 1: 在 pages/workspace 分包中注册 2 个新页面**

在 `storycanvas-mobile/src/pages.json` 中找到 `pages/workspace` 分包的 `pages` 数组（包含 `chapter-view`、`screenplay`、`shot-list` 等已有页面），在数组末尾追加 2 个新页面：

```json
{
  "path": "pages/workspace/video-workflow",
  "style": {
    "navigationBarTitleText": "视频工作流",
    "navigationBarBackgroundColor": "#ffffff",
    "navigationBarTextStyle": "black"
  }
},
{
  "path": "pages/workspace/video-shots",
  "style": {
    "navigationBarTitleText": "镜头列表",
    "navigationBarBackgroundColor": "#ffffff",
    "navigationBarTextStyle": "black"
  }
}
```

注意：确保追加的位置在 `pages/workspace` 分包的 `pages` 数组内，不在其他分包中。确保 JSON 语法正确（前一个对象末尾有逗号）。

- [ ] **Step 2: 验证 JSON 语法正确**

Run: `cd storycanvas-mobile && node -e "require('./src/pages.json')" 2>&1 || echo "JSON parse check via type-check instead"`
备用验证：Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd storycanvas-mobile
git add src/pages.json
git commit -m "feat(mobile): register video-workflow and video-shots pages"
```

---

## Task 9: video-workflow.vue 工作流管理页面

**Files:**
- Create: `storycanvas-mobile/src/pages/workspace/video-workflow.vue`

- [ ] **Step 1: 创建工作流管理页面**

创建 `storycanvas-mobile/src/pages/workspace/video-workflow.vue`：

```vue
<template>
  <view class="video-workflow">
    <lv-navbar title="视频工作流" show-back />

    <view class="video-workflow__content">
      <!-- 章节选择器 -->
      <view class="video-workflow__section">
        <text class="video-workflow__section-title">选择章节</text>
        <view class="video-workflow__chapter-list">
          <view
            v-for="ch in chapters"
            :key="ch.id"
            :class="['video-workflow__chapter-item', { 'video-workflow__chapter-item--active': activeChapterId === ch.id }]"
            @tap="selectChapter(ch.id)"
          >
            <text class="video-workflow__chapter-title">第{{ ch.chapter_number }}章 {{ ch.title || '' }}</text>
          </view>
        </view>
      </view>

      <!-- 工作流列表 -->
      <view class="video-workflow__section">
        <text class="video-workflow__section-title">工作流列表</text>

        <view v-if="loading" class="video-workflow__loading">
          <lv-loading />
        </view>

        <view v-else-if="workflows.length === 0" class="video-workflow__empty">
          <lv-empty title="暂无工作流" description="点击右下角按钮创建">
          </lv-empty>
        </view>

        <view v-else class="video-workflow__list">
          <view
            v-for="wf in workflows"
            :key="wf.id"
            class="video-workflow__card"
            @tap="goToShots(wf.id)"
          >
            <view class="video-workflow__card-header">
              <text class="video-workflow__card-title">工作流 #{{ wf.id }}</text>
              <view :class="['video-workflow__status-badge', `video-workflow__status-badge--${wf.workflow_status}`]">
                <text>{{ statusLabel(wf.workflow_status) }}</text>
              </view>
            </view>

            <view class="video-workflow__card-stats">
              <view class="video-workflow__stat">
                <text class="video-workflow__stat-value">{{ wf.total_shots }}</text>
                <text class="video-workflow__stat-label">总镜头</text>
              </view>
              <view class="video-workflow__stat">
                <text class="video-workflow__stat-value">{{ wf.completed_shots }}</text>
                <text class="video-workflow__stat-label">已完成</text>
              </view>
              <view class="video-workflow__stat">
                <text class="video-workflow__stat-value">{{ wf.failed_shots }}</text>
                <text class="video-workflow__stat-label">失败</text>
              </view>
            </view>

            <view v-if="wf.message" class="video-workflow__card-message">
              <text>{{ wf.message }}</text>
            </view>

            <view class="video-workflow__card-actions" @tap.stop>
              <lv-button size="sm" @tap="goToShots(wf.id)">继续</lv-button>
              <lv-button size="sm" secondary @tap="handleConcat(wf.id)" :loading="concatenating">拼接</lv-button>
              <lv-button size="sm" secondary @tap="handleReset(wf.id)">重置</lv-button>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 新建工作流浮动按钮 -->
    <lv-fab @tap="showCreateModal = true" />

    <!-- 新建工作流弹窗 -->
    <lv-modal
      v-model:show="showCreateModal"
      title="新建视频工作流"
      @confirm="handleCreateWorkflow"
      :confirm-loading="creating"
    >
      <view class="video-workflow__modal-content">
        <!-- 风格选择 -->
        <view class="video-workflow__field">
          <text class="video-workflow__field-label">视频风格</text>
          <view class="video-workflow__style-grid">
            <view
              v-for="preset in stylePresets"
              :key="preset.id"
              :class="['video-workflow__style-item', { 'video-workflow__style-item--active': selectedStylePresetId === preset.id }]"
              @tap="selectedStylePresetId = preset.id; store.selectedStyle = preset.name"
            >
              <image
                v-if="preset.image_url"
                :src="preset.image_url"
                class="video-workflow__style-image"
                mode="aspectFill"
              />
              <view v-else class="video-workflow__style-placeholder">
                <lv-icon name="Palette" :size="20" color="#94a3b8" />
              </view>
              <text class="video-workflow__style-name">{{ preset.name }}</text>
            </view>
          </view>
        </view>

        <!-- 视频比例 -->
        <view class="video-workflow__field">
          <text class="video-workflow__field-label">视频比例</text>
          <view class="video-workflow__ratio-group">
            <view
              :class="['video-workflow__ratio-btn', { 'video-workflow__ratio-btn--active': store.videoAspectRatio === '16:9' }]"
              @tap="store.videoAspectRatio = '16:9'"
            >
              <text>16:9 横屏</text>
            </view>
            <view
              :class="['video-workflow__ratio-btn', { 'video-workflow__ratio-btn--active': store.videoAspectRatio === '9:16' }]"
              @tap="store.videoAspectRatio = '9:16'"
            >
              <text>9:16 竖屏</text>
            </view>
          </view>
        </view>

        <!-- 风格参考图上传 -->
        <view class="video-workflow__field">
          <text class="video-workflow__field-label">风格参考图（可选）</text>
          <view class="video-workflow__upload-area" @tap="handleUploadStyleImage">
            <image
              v-if="store.styleReferenceImageUrl"
              :src="store.styleReferenceImageUrl"
              class="video-workflow__upload-preview"
              mode="aspectFill"
            />
            <view v-else class="video-workflow__upload-placeholder">
              <lv-icon name="ImagePlus" :size="24" color="#94a3b8" />
              <text class="video-workflow__upload-text">点击上传参考图</text>
            </view>
          </view>
        </view>
      </view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useStoriesStore } from '@/stores/stories'
import { videoApi } from '@/api'
import { chooseImages } from '@/utils/upload'
import type { Chapter } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvFab from '@/components/lv-fab/lv-fab.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const store = useVideoWorkflowStore()
const storyStore = useStoriesStore()

const activeChapterId = ref<number>(0)
const chapters = ref<Chapter[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const creating = ref(false)
const concatenating = ref(false)
const selectedStylePresetId = ref<number | null>(null)

const workflows = computed(() => store.workflows)

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: '空闲',
    parsing_shots: '拆镜中',
    generating_details: '生成详情中',
    generating_storyboards: '生成故事版中',
    generating_videos: '生成视频中',
    reanalyzing_prompts: '分析提示词中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

function selectChapter(chapterId: number) {
  activeChapterId.value = chapterId
  loadWorkflows(chapterId)
}

async function loadWorkflows(chapterId: number) {
  loading.value = true
  try {
    await store.fetchWorkflows(chapterId)
  } finally {
    loading.value = false
  }
}

function goToShots(workflowId: number) {
  uni.navigateTo({ url: `/pages/workspace/video-shots?workflowId=${workflowId}` })
}

async function handleCreateWorkflow() {
  if (!activeChapterId.value) {
    uni.showToast({ title: '请先选择章节', icon: 'none' })
    return
  }
  creating.value = true
  try {
    const payload: any = {
      chapter_id: activeChapterId.value,
      video_style: store.selectedStyle,
    }
    if (store.styleReferenceImageUrl) {
      payload.style_reference_image_url = store.styleReferenceImageUrl
    }
    await store.createWorkflow(payload)
    showCreateModal.value = false
    uni.showToast({ title: '工作流已创建', icon: 'success' })
    await loadWorkflows(activeChapterId.value)
    if (store.activeWorkflow) {
      goToShots(store.activeWorkflow.id)
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '创建失败', icon: 'none' })
  } finally {
    creating.value = false
  }
}

async function handleConcat(workflowId: number) {
  concatenating.value = true
  try {
    const result = await store.concatVideo(workflowId)
    uni.showToast({ title: '视频拼接完成', icon: 'success' })
    if (result.video_url) {
      // 预览拼接视频
      uni.navigateTo({
        url: `/pages/workspace/render-jobs?workflowId=${workflowId}&concatUrl=${encodeURIComponent(result.video_url)}`
      })
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '拼接失败', icon: 'none' })
  } finally {
    concatenating.value = false
  }
}

async function handleReset(workflowId: number) {
  uni.showModal({
    title: '确认重置',
    content: '重置将清除所有镜头、故事版和视频数据，是否继续？',
    success: async (res) => {
      if (res.confirm) {
        try {
          await store.resetWorkflow(workflowId)
          uni.showToast({ title: '已重置', icon: 'success' })
          await loadWorkflows(activeChapterId.value)
        } catch (e: any) {
          uni.showToast({ title: e.message || '重置失败', icon: 'none' })
        }
      }
    }
  })
}

async function handleUploadStyleImage() {
  try {
    const paths = await chooseImages(1)
    if (paths.length === 0) return
    // 先创建临时工作流或直接上传到章节
    // 这里先存储路径，等创建工作流时一起提交
    store.styleReferenceImageUrl = paths[0]
    uni.showToast({ title: '参考图已选择', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '选择图片失败', icon: 'none' })
  }
}

onMounted(async () => {
  // 从页面参数获取 chapterId
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const chapterId = Number(page.options?.chapterId || 0)

  // 加载章节列表
  if (storyStore.activeStoryId) {
    // 从 stories store 获取章节列表
    // 这里简化处理，实际需要从 workspace store 或 API 获取
  }

  // 加载风格预设
  await store.loadStylePresets()

  if (chapterId) {
    activeChapterId.value = chapterId
    await loadWorkflows(chapterId)
  }
})
</script>

<style lang="scss" scoped>
.video-workflow {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding 120rpx;
  }

  &__section {
    margin-bottom: 32rpx;
  }

  &__section-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
    display: block;
  }

  &__chapter-list {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
  }

  &__chapter-item {
    padding: 12rpx 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    border: 2rpx solid transparent;

    &--active {
      border-color: $lv-primary;
      background: $lv-primary-light;
    }
  }

  &__chapter-title {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding: 60rpx 0;
  }

  &__empty {
    padding: 40rpx 0;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: 24rpx;
    padding: 24rpx;
    margin-bottom: 16rpx;
  }

  &__card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16rpx;
  }

  &__card-title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__status-badge {
    padding: 4rpx 16rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;

    &--idle { background: #f1f5f9; color: #64748b; }
    &--parsing_shots, &--generating_details, &--generating_storyboards, &--generating_videos, &--reanalyzing_prompts {
      background: #dbeafe; color: #2563eb;
    }
    &--completed { background: #dcfce7; color: #16a34a; }
    &--failed { background: #fee2e2; color: #dc2626; }
  }

  &__card-stats {
    display: flex;
    gap: 32rpx;
    margin-bottom: 16rpx;
  }

  &__stat {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  &__stat-value {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__stat-label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__card-message {
    margin-bottom: 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__card-actions {
    display: flex;
    gap: 12rpx;
  }

  // Modal 内容样式
  &__modal-content {
    padding: 16rpx 0;
  }

  &__field {
    margin-bottom: 24rpx;
  }

  &__field-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
    display: block;
  }

  &__style-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
  }

  &__style-item {
    width: 140rpx;
    border-radius: $lv-radius-md;
    overflow: hidden;
    border: 2rpx solid transparent;
    background: $lv-surface-solid;

    &--active {
      border-color: $lv-primary;
    }
  }

  &__style-image {
    width: 140rpx;
    height: 100rpx;
    display: block;
  }

  &__style-placeholder {
    width: 140rpx;
    height: 100rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    background: $lv-primary-lighter;
  }

  &__style-name {
    font-size: $lv-font-xs;
    color: $lv-text-primary;
    padding: 8rpx;
    text-align: center;
    display: block;
  }

  &__ratio-group {
    display: flex;
    gap: 12rpx;
  }

  &__ratio-btn {
    flex: 1;
    padding: 16rpx;
    text-align: center;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    border: 2rpx solid transparent;

    &--active {
      border-color: $lv-primary;
      background: $lv-primary-light;
    }
  }

  &__upload-area {
    width: 100%;
    height: 200rpx;
    border-radius: $lv-radius-md;
    overflow: hidden;
    background: $lv-surface-solid;
  }

  &__upload-preview {
    width: 100%;
    height: 100%;
  }

  &__upload-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8rpx;
  }

  &__upload-text {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }
}
</style>
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/pages/workspace/video-workflow.vue`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
cd storycanvas-mobile
git add src/pages/workspace/video-workflow.vue
git commit -m "feat(mobile): add video-workflow page for workflow management"
```

---

## Task 10: video-shots.vue 镜头列表页面

**Files:**
- Create: `storycanvas-mobile/src/pages/workspace/video-shots.vue`

- [ ] **Step 1: 创建镜头列表页面**

创建 `storycanvas-mobile/src/pages/workspace/video-shots.vue`：

```vue
<template>
  <view class="video-shots">
    <lv-navbar title="镜头列表" show-back />

    <view class="video-shots__content">
      <!-- 工作流状态栏 -->
      <view v-if="workflow" class="video-shots__status-bar">
        <view class="video-shots__status-info">
          <text class="video-shots__status-text">{{ statusLabel(workflow.workflow_status) }}</text>
          <text class="video-shots__status-progress">{{ workflow.completed_shots }}/{{ workflow.total_shots }}</text>
        </view>
        <view class="video-shots__progress-bar">
          <view class="video-shots__progress-fill" :style="{ width: progressPercent + '%' }" />
        </view>
      </view>

      <!-- 加载中 -->
      <view v-if="loading" class="video-shots__loading">
        <lv-loading />
      </view>

      <template v-else>
        <!-- 无镜头时：显示拆镜按钮 -->
        <view v-if="shots.length === 0" class="video-shots__empty">
          <lv-empty title="暂无镜头" description="点击下方按钮开始拆镜">
            <template #action>
              <lv-button @tap="handleParseShots" :loading="parsing">开始拆镜</lv-button>
            </template>
          </lv-empty>
        </view>

        <!-- 镜头列表 -->
        <template v-else>
          <!-- 批量操作栏 -->
          <view class="video-shots__batch-bar">
            <view class="video-shots__batch-left">
              <view class="video-shots__select-all" @tap="toggleSelectAll">
                <view :class="['video-shots__checkbox', { 'video-shots__checkbox--checked': allSelected }]" />
                <text>全选</text>
              </view>
              <text class="video-shots__selected-count">已选 {{ store.selectedShotIds.length }}</text>
            </view>
            <view class="video-shots__batch-actions">
              <lv-button size="sm" secondary @tap="handleBatchStoryboards" :loading="batchGenerating" :disabled="store.selectedShotIds.length === 0">
                批量故事版
              </lv-button>
              <lv-button size="sm" secondary @tap="handleBatchVideos" :loading="batchGenerating" :disabled="store.selectedShotIds.length === 0">
                批量视频
              </lv-button>
            </view>
          </view>

          <!-- 镜头卡片列表 -->
          <view class="video-shots__list">
            <view
              v-for="shot in shots"
              :key="shot.id"
              :class="['video-shots__card', { 'video-shots__card--selected': store.selectedShotIds.includes(shot.id), 'video-shots__card--skipped': store.skippedShotIds.includes(shot.id) }]"
              @tap="goToShotDetail(shot.id)"
            >
              <!-- 复选框 -->
              <view class="video-shots__card-checkbox" @tap.stop="store.toggleShotSelection(shot.id)">
                <view :class="['video-shots__checkbox', { 'video-shots__checkbox--checked': store.selectedShotIds.includes(shot.id) }]" />
              </view>

              <!-- 镜头信息 -->
              <view class="video-shots__card-body">
                <view class="video-shots__card-header">
                  <text class="video-shots__card-index">镜头 {{ shot.shot_index + 1 }}</text>
                  <view :class="['video-shots__shot-status', `video-shots__shot-status--${shot.status}`]">
                    <text>{{ shotStatusLabel(shot.status) }}</text>
                  </view>
                </view>

                <text v-if="shot.story_summary" class="video-shots__card-summary">{{ shot.story_summary }}</text>

                <view class="video-shots__card-meta">
                  <text v-if="shot.scene_location" class="video-shots__card-meta-item">{{ shot.scene_location }}</text>
                  <text v-if="shot.camera_plan" class="video-shots__card-meta-item">{{ shot.camera_plan }}</text>
                </view>

                <!-- 缩略图预览 -->
                <view class="video-shots__card-thumbnails">
                  <view class="video-shots__thumbnail">
                    <image
                      v-if="shot.storyboard_image_url"
                      :src="shot.storyboard_image_url"
                      class="video-shots__thumbnail-img"
                      mode="aspectFill"
                    />
                    <view v-else class="video-shots__thumbnail-placeholder">
                      <lv-icon name="Image" :size="16" color="#94a3b8" />
                    </view>
                    <text class="video-shots__thumbnail-label">故事版</text>
                  </view>
                  <view class="video-shots__thumbnail">
                    <view v-if="shot.video_url" class="video-shots__thumbnail-video">
                      <lv-icon name="Play" :size="20" color="#fff" />
                    </view>
                    <view v-else class="video-shots__thumbnail-placeholder">
                      <lv-icon name="Video" :size="16" color="#94a3b8" />
                    </view>
                    <text class="video-shots__thumbnail-label">视频</text>
                  </view>
                </view>
              </view>
            </view>
          </view>
        </template>
      </template>
    </view>

    <!-- 底部操作栏 -->
    <view v-if="shots.length > 0" class="video-shots__bottom-bar">
      <lv-button v-if="!hasDetails" size="sm" secondary @tap="handleGenerateDetails" :loading="parsing">
        生成详情
      </lv-button>
      <lv-button @tap="handleConcat" :loading="concatenating" :disabled="!allVideosReady">
        拼接视频
      </lv-button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onShow, onHidden } from 'vue'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useVideoGenStore } from '@/stores/videoGen'
import { useWorkflowPolling } from '@/composables/useWorkflowPolling'
import type { ChapterVideoShot } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const store = useVideoWorkflowStore()
const videoGenStore = useVideoGenStore()

const workflowId = ref<number>(0)
const loading = ref(false)
const parsing = ref(false)
const batchGenerating = ref(false)
const concatenating = ref(false)

const workflow = computed(() => store.currentWorkflow)
const shots = computed(() => store.currentShots)

const allSelected = computed(() =>
  shots.value.length > 0 &&
  shots.value.every(s => store.selectedShotIds.includes(s.id) || store.skippedShotIds.includes(s.id))
)

const progressPercent = computed(() => {
  if (!workflow.value || workflow.value.total_shots === 0) return 0
  return Math.round((workflow.value.completed_shots / workflow.value.total_shots) * 100)
})

const hasDetails = computed(() =>
  shots.value.length > 0 && shots.value.some(s => s.camera_plan || s.motion_plan)
)

const allVideosReady = computed(() =>
  shots.value.length > 0 && shots.value.every(s => s.video_url || store.skippedShotIds.includes(s.id))
)

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: '空闲',
    parsing_shots: '拆镜中',
    generating_details: '生成详情中',
    generating_storyboards: '生成故事版中',
    generating_videos: '生成视频中',
    reanalyzing_prompts: '分析提示词中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

function shotStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '待处理',
    parsing: '拆镜中',
    details_ready: '详情就绪',
    storyboard_generating: '故事版生成中',
    storyboard_ready: '故事版就绪',
    video_generating: '视频生成中',
    video_ready: '视频就绪',
    failed: '失败',
  }
  return labels[status] || status
}

function toggleSelectAll() {
  if (allSelected.value) {
    store.clearSelection()
  } else {
    store.selectAllShots()
  }
}

function goToShotDetail(shotId: number) {
  uni.navigateTo({
    url: `/pages/workspace/storyboard?workflowId=${workflowId.value}&shotId=${shotId}`
  })
}

async function loadWorkflow() {
  loading.value = true
  try {
    await store.loadWorkflowDetail(workflowId.value)
    await store.loadChapterAssets(workflow.value?.chapter_id || 0)
  } finally {
    loading.value = false
  }
}

async function handleParseShots() {
  parsing.value = true
  try {
    await store.parseShots(workflowId.value)
    uni.showToast({ title: '拆镜完成', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '拆镜失败', icon: 'none' })
  } finally {
    parsing.value = false
  }
}

async function handleGenerateDetails() {
  parsing.value = true
  try {
    const shotIds = shots.value.map(s => s.id)
    await store.generateShotDetails(workflowId.value, shotIds)
    uni.showToast({ title: '详情生成完成', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    parsing.value = false
  }
}

async function handleBatchStoryboards() {
  if (store.selectedShotIds.length === 0) {
    uni.showToast({ title: '请先选择镜头', icon: 'none' })
    return
  }
  batchGenerating.value = true
  try {
    // 为每个选中镜头启动 videoGenStore 状态
    store.selectedShotIds.forEach(id => videoGenStore.startJob(id, 0, 'storyboard'))
    await store.generateStoryboards(workflowId.value, store.selectedShotIds)
    uni.showToast({ title: '故事版生成已提交', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    batchGenerating.value = false
  }
}

async function handleBatchVideos() {
  if (store.selectedShotIds.length === 0) {
    uni.showToast({ title: '请先选择镜头', icon: 'none' })
    return
  }
  batchGenerating.value = true
  try {
    store.selectedShotIds.forEach(id => videoGenStore.startJob(id, 0))
    await store.generateVideos(workflowId.value, store.selectedShotIds)
    uni.showToast({ title: '视频生成已提交', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    batchGenerating.value = false
  }
}

async function handleConcat() {
  concatenating.value = true
  try {
    const result = await store.concatVideo(workflowId.value)
    uni.showToast({ title: '拼接完成', icon: 'success' })
    if (result.video_url) {
      uni.navigateTo({
        url: `/pages/workspace/render-jobs?workflowId=${workflowId.value}&concatUrl=${encodeURIComponent(result.video_url)}`
      })
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '拼接失败', icon: 'none' })
  } finally {
    concatenating.value = false
  }
}

// 工作流轮询
const workflowIdRef = computed(() => workflowId.value || null)
const { isPolling, start: startPolling, stop: stopPolling } = useWorkflowPolling(workflowIdRef)

onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  workflowId.value = Number(page.options?.workflowId || 0)
  if (!workflowId.value) {
    uni.showToast({ title: '参数错误', icon: 'none' })
    return
  }
  await loadWorkflow()
  startPolling()
})

// 页面隐藏时暂停轮询，显示时恢复
onShow(() => {
  if (workflowId.value) {
    loadWorkflow()
    startPolling()
  }
})

onHidden(() => {
  stopPolling()
})
</script>

<style lang="scss" scoped>
.video-shots {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding 120rpx;
  }

  &__status-bar {
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 16rpx 24rpx;
    margin-bottom: 20rpx;
  }

  &__status-info {
    display: flex;
    justify-content: space-between;
    margin-bottom: 12rpx;
  }

  &__status-text {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    font-weight: 500;
  }

  &__status-progress {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__progress-bar {
    height: 6rpx;
    background: $lv-border-light;
    border-radius: 3rpx;
    overflow: hidden;
  }

  &__progress-fill {
    height: 100%;
    background: $lv-primary;
    transition: width 0.3s ease;
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding: 80rpx 0;
  }

  &__empty {
    padding: 60rpx 0;
  }

  &__batch-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 16rpx 24rpx;
    margin-bottom: 16rpx;
    position: sticky;
    top: 0;
    z-index: 10;
  }

  &__batch-left {
    display: flex;
    align-items: center;
    gap: 16rpx;
  }

  &__select-all {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__checkbox {
    width: 32rpx;
    height: 32rpx;
    border: 2rpx solid $lv-border;
    border-radius: 6rpx;

    &--checked {
      background: $lv-primary;
      border-color: $lv-primary;
    }
  }

  &__selected-count {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__batch-actions {
    display: flex;
    gap: 12rpx;
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: 24rpx;
    padding: 24rpx;
    display: flex;
    gap: 16rpx;
    border: 2rpx solid transparent;

    &--selected {
      border-color: $lv-primary;
    }

    &--skipped {
      opacity: 0.5;
    }
  }

  &__card-checkbox {
    padding-top: 4rpx;
  }

  &__card-body {
    flex: 1;
  }

  &__card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8rpx;
  }

  &__card-index {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__shot-status {
    padding: 2rpx 12rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;

    &--pending { background: #f1f5f9; color: #64748b; }
    &--parsing, &--storyboard_generating, &--video_generating { background: #dbeafe; color: #2563eb; }
    &--details_ready, &--storyboard_ready { background: #fef3c7; color: #d97706; }
    &--video_ready { background: #dcfce7; color: #16a34a; }
    &--failed { background: #fee2e2; color: #dc2626; }
  }

  &__card-summary {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.5;
    margin-bottom: 8rpx;
  }

  &__card-meta {
    display: flex;
    gap: 12rpx;
    flex-wrap: wrap;
    margin-bottom: 12rpx;
  }

  &__card-meta-item {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    background: $lv-primary-lighter;
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-sm;
  }

  &__card-thumbnails {
    display: flex;
    gap: 12rpx;
  }

  &__thumbnail {
    width: 120rpx;
  }

  &__thumbnail-img {
    width: 120rpx;
    height: 80rpx;
    border-radius: $lv-radius-sm;
    display: block;
  }

  &__thumbnail-placeholder {
    width: 120rpx;
    height: 80rpx;
    border-radius: $lv-radius-sm;
    background: $lv-primary-lighter;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__thumbnail-video {
    width: 120rpx;
    height: 80rpx;
    border-radius: $lv-radius-sm;
    background: #1e293b;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__thumbnail-label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    text-align: center;
    display: block;
    margin-top: 4rpx;
  }

  &__bottom-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    gap: 16rpx;
    padding: 16rpx 24rpx calc(env(safe-area-inset-bottom) + 16rpx);
    background: $lv-surface-solid;
    box-shadow: 0 -4rpx 12rpx rgba(0, 0, 0, 0.05);
    z-index: 100;
  }
}
</style>
```

- [ ] **Step 2: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 3: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/pages/workspace/video-shots.vue`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
cd storycanvas-mobile
git add src/pages/workspace/video-shots.vue
git commit -m "feat(mobile): add video-shots page for shot list and batch operations"
```

---

## Task 11: chapter-view.vue 添加视频标签

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/chapter-view.vue`

- [ ] **Step 1: 修改 tabs 数组，插入「视频」标签**

在 `storycanvas-mobile/src/pages/workspace/chapter-view.vue` 第 20 行，将 tabs 数组从：
```vue
      :tabs="['框架', '编辑', '漫画', '助手']"
```
改为：
```vue
      :tabs="['框架', '编辑', '漫画', '视频', '助手']"
```

- [ ] **Step 2: 在漫画标签（#tab-2）结束后、助手标签之前插入视频标签**

在第 379 行 `</template>`（漫画标签结束）之后、第 381 行 `<!-- 助手标签 -->` 之前，插入新的视频标签模板：

```vue
      <!-- 视频标签 -->
      <template #tab-3>
        <scroll-view scroll-y class="chapter-view__tab-scroll">
          <view class="chapter-view__tab">
            <!-- 视频工作流入口卡 -->
            <view class="video-entry-card" @tap="goToVideoWorkflow">
              <view class="video-entry-card__icon">
                <lv-icon name="Video" :size="40" color="#2563eb" />
              </view>
              <view class="video-entry-card__body">
                <text class="video-entry-card__title">视频工作流</text>
                <text class="video-entry-card__desc">创建视频工作流，AI 自动拆镜生成分镜视频</text>
              </view>
              <lv-icon name="ChevronRight" :size="20" color="#94a3b8" />
            </view>

            <!-- 已有工作流快捷入口 -->
            <view v-if="videoWorkflows.length > 0" class="video-entry-list">
              <text class="video-entry-list__title">已有工作流</text>
              <view
                v-for="wf in videoWorkflows"
                :key="wf.id"
                class="video-entry-item"
                @tap="goToVideoShots(wf.id)"
              >
                <view class="video-entry-item__info">
                  <text class="video-entry-item__title">工作流 #{{ wf.id }}</text>
                  <text class="video-entry-item__meta">{{ wf.completed_shots }}/{{ wf.total_shots }} 镜头</text>
                </view>
                <view :class="['video-entry-item__status', `video-entry-item__status--${wf.workflow_status}`]">
                  <text>{{ videoStatusLabel(wf.workflow_status) }}</text>
                </view>
              </view>
            </view>
          </view>
        </scroll-view>
      </template>
```

- [ ] **Step 3: 将原助手标签的 slot 名从 #tab-3 改为 #tab-4**

在第 382 行（原来的 `<!-- 助手标签 -->` 部分），将：
```vue
      <!-- 助手标签 -->
      <template #tab-3>
```
改为：
```vue
      <!-- 助手标签 -->
      <template #tab-4>
```

- [ ] **Step 4: 在 script setup 中添加视频相关的 import 和逻辑**

在 `<script setup>` 标签内的 import 区域（约第 440-460 行），添加：

```typescript
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { videoApi } from '@/api'
import type { ChapterVideoWorkflow } from '@/api/types'
```

在变量定义区域（约第 485 行 `const activeTabIndex = ref(0)` 附近），添加：

```typescript
const videoWorkflowStore = useVideoWorkflowStore()
const videoWorkflows = ref<ChapterVideoWorkflow[]>([])

function videoStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: '空闲',
    parsing_shots: '拆镜中',
    generating_details: '生成详情中',
    generating_storyboards: '生成故事版中',
    generating_videos: '生成视频中',
    reanalyzing_prompts: '分析提示词中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

async function loadVideoWorkflows() {
  if (workspaceStore.activeChapterId) {
    try {
      const result = await videoApi.listChapterVideoWorkflows(workspaceStore.activeChapterId)
      videoWorkflows.value = result.workflows || []
    } catch {
      videoWorkflows.value = []
    }
  }
}

function goToVideoWorkflow() {
  const chapterId = workspaceStore.activeChapterId
  if (!chapterId) {
    uni.showToast({ title: '请先选择章节', icon: 'none' })
    return
  }
  uni.navigateTo({ url: `/pages/workspace/video-workflow?chapterId=${chapterId}` })
}

function goToVideoShots(workflowId: number) {
  uni.navigateTo({ url: `/pages/workspace/video-shots?workflowId=${workflowId}` })
}
```

- [ ] **Step 5: 在 tab 切换 watch 中添加视频标签的加载逻辑**

找到 `watch(() => activeTabIndex.value, async (tabIndex) => {` （约第 954 行），在 watch 回调中添加视频标签的加载逻辑。在现有的助手 tab 加载逻辑之后追加：

```typescript
    // 切换到视频标签（tabIndex === 3）时加载工作流列表
    if (tabIndex === 3) {
      loadVideoWorkflows()
    }
```

- [ ] **Step 6: 添加视频入口卡的样式**

在 `<style>` 块末尾（约第 1838 行 `}` 之前，`.chapter-view` 的闭合大括号内），追加：

```scss
  // --- Video entry ---
  &__video-entry-card {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    margin-bottom: 20rpx;

    &:active { opacity: 0.8; }
  }

  &__video-entry-icon {
    width: 80rpx;
    height: 80rpx;
    border-radius: $lv-radius-md;
    background: $lv-primary-light;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  &__video-entry-body {
    flex: 1;
  }

  &__video-entry-title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    display: block;
    margin-bottom: 4rpx;
  }

  &__video-entry-desc {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__video-entry-list {
    margin-top: 16rpx;
  }

  &__video-entry-list-title {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
    display: block;
  }

  &__video-entry-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16rpx 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    margin-bottom: 12rpx;

    &:active { opacity: 0.8; }
  }

  &__video-entry-item-info {
    flex: 1;
  }

  &__video-entry-item-title {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    font-weight: 500;
    display: block;
  }

  &__video-entry-item-meta {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__video-entry-item-status {
    padding: 4rpx 16rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;

    &--idle { background: #f1f5f9; color: #64748b; }
    &--parsing_shots, &--generating_details, &--generating_storyboards, &--generating_videos, &--reanalyzing_prompts {
      background: #dbeafe; color: #2563eb;
    }
    &--completed { background: #dcfce7; color: #16a34a; }
    &--failed { background: #fee2e2; color: #dc2626; }
  }
```

- [ ] **Step 7: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 8: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/pages/workspace/chapter-view.vue`
Expected: 无错误

- [ ] **Step 9: Commit**

```bash
cd storycanvas-mobile
git add src/pages/workspace/chapter-view.vue
git commit -m "feat(mobile): add video tab to chapter-view with workflow entry"
```

---

## Task 12: workspace/index.vue 添加视频创作入口

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/index.vue`

- [ ] **Step 1: 在 workspace/index.vue 的 actions 区域添加视频创作入口**

在 `storycanvas-mobile/src/pages/workspace/index.vue` 的模板中，找到 `<view class="workspace-page__actions">`（约第 37 行），在 `goWorkspace` 按钮之后追加视频创作入口：

```vue
        <view class="workspace-page__actions">
          <lv-button block @tap="goWorkspace">进入工作台</lv-button>
          <lv-button block secondary @tap="goVideoWorkflow">
            <lv-icon name="Video" :size="16" color="#2563eb" style="margin-right: 8rpx;" />视频创作
          </lv-button>
          <lv-button v-if="!storyStore.activeStory.onboarding_completed" secondary block @tap="goOnboarding">
            <lv-icon name="Sparkles" :size="16" color="#2563eb" style="margin-right: 8rpx;" />引导创作
          </lv-button>
        </view>
```

- [ ] **Step 2: 在 script setup 中添加视频创作跳转函数**

在 `storycanvas-mobile/src/pages/workspace/index.vue` 的 `<script setup>` 中，在 `goWorkspace` 函数之后追加：

```typescript
function goVideoWorkflow() {
  if (storyStore.activeStory) {
    uni.navigateTo({ url: `/pages/workspace/video-workflow` })
  }
}
```

- [ ] **Step 3: 验证类型检查通过**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS

- [ ] **Step 4: LSP 诊断**

Run: `lsp_diagnostics` on `storycanvas-mobile/src/pages/workspace/index.vue`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
cd storycanvas-mobile
git add src/pages/workspace/index.vue
git commit -m "feat(mobile): add video creation entry to workspace page"
```

---

## Task 13: 构建验证和集成测试

**Files:**
- 无新文件修改，仅验证

- [ ] **Step 1: 完整类型检查**

Run: `cd storycanvas-mobile && npm run type-check`
Expected: PASS (无错误)

- [ ] **Step 2: H5 生产构建**

Run: `cd storycanvas-mobile && npm run build:h5`
Expected: 构建成功，无编译错误

- [ ] **Step 3: LSP 诊断所有新增/修改文件**

Run: `lsp_diagnostics` on:
- `storycanvas-mobile/src/api/types.ts`
- `storycanvas-mobile/src/api/video.ts`
- `storycanvas-mobile/src/stores/videoGen.ts`
- `storycanvas-mobile/src/stores/videoWorkflow.ts`
- `storycanvas-mobile/src/composables/useWorkflowPolling.ts`
- `storycanvas-mobile/src/utils/upload.ts`
- `storycanvas-mobile/src/pages/workspace/video-workflow.vue`
- `storycanvas-mobile/src/pages/workspace/video-shots.vue`
- `storycanvas-mobile/src/pages/workspace/chapter-view.vue`
- `storycanvas-mobile/src/pages/workspace/index.vue`

Expected: 所有文件无错误

- [ ] **Step 4: H5 开发服务器手动验证**

Run: `cd storycanvas-mobile && npm run dev:h5`

在浏览器中验证：
1. 打开 `http://localhost:5174`
2. 登录后进入创作中心
3. 确认看到「视频创作」按钮
4. 点击进入视频工作流页面
5. 确认风格预设加载正常
6. 在章节工作台确认第 4 个标签为「视频」
7. 点击视频标签确认入口卡显示正常

- [ ] **Step 5: Commit 验证通过标记**

```bash
cd storycanvas-mobile
git add -A
git commit -m "test(mobile): verify phase 1 build and type-check pass"
```

---

## 后续阶段

阶段一完成后，后续阶段将在新的实施计划中定义：

**阶段二（工作台完整）**：新增 `video-shot-detail.vue`（4 工作台 tab），实现所有单镜操作（生成/上传/删除/重绘/保存提示词/重新分析/预览），引用资产选择器组件，风格预设选择弹窗，提示词编辑器组件。

**阶段三（增强功能）**：角色库版本管理集成，角色参考图生成/重绘，视频任务重试/片段管理，资产管理面板，与现有页面的完整跳转联动，videoGenStore 过期清理定时任务。
