# 移动端视频工作流移植设计文档

**日期**：2026-06-18
**主题**：将 web 端视频工作流模块（Chapter Video Workflow 新版流水线）一比一复刻移植到移动端（storycanvas-mobile）

---

## 一、背景与目标

### 1.1 现状

StoryCanvas 移动端（`storycanvas-mobile/`，Vue 3 + uni-app + Pinia + TypeScript）已建成完整的移动应用，功能覆盖率达 70% 以上。视频管线方面已有：
- API 层 21 个函数（覆盖部分后端端点）
- `videoWorkflow.ts` Pinia store 基本框架
- 5 个末端页面：`screenplay.vue`、`shot-list.vue`、`storyboard.vue`、`video-characters.vue`、`render-jobs.vue`
- 5 个 Prompt 模板文件
- 42 个自研 UI 组件（lv-* 系列）
- 跨平台 SSE 引擎

**缺失的核心**：web 端新版流水线的三大核心组件在移动端不存在：
- `VideoStoryboardLayout`（工作流壳层，708 行）
- `ChapterVideoWorkflowPanel`（主面板，1200+ 行）
- `VideoCardWorkbench`（工作台弹窗，759 行）

API 层缺口也较大：移动端 21 个 API 函数，web 端 50+，缺少拆镜、批量生成、重置、提示词分析、资产管理、角色库版本、风格预设等关键 API。

### 1.2 目标

将 web 端新版 Chapter Video Workflow 流水线完整移植到移动端，实现：
- 工作流创建 → 拆镜 → 生成镜头详情 → 批量生成故事版 → 批量生成视频 → 整章拼接的完整流程
- 每镜 4 个工作台（character/storyboard/video/scene）的全部操作
- 工作流状态实时轮询和进度反馈
- 风格预设选择和引用资产管理
- 与现有 5 个页面的跳转联动

### 1.3 移植范围

**移植**：新版 Chapter Video Workflow 流水线全部功能
**不移植**：旧版流水线功能（首尾帧生成、画刷局部重绘、SSE 流式视频生成、7 section 资产管理面板）

---

## 二、架构概览

### 2.1 整体架构

```
入口层
  ├─ chapter-view.vue 第 5 标签「视频」→ 跳转 video-workflow.vue
  └─ workspace/index.vue 视频创作卡片 → 跳转 video-workflow.vue

页面层（新增 3 页面）
  ├─ video-workflow.vue     工作流管理（创建/列表/状态轮询/风格选择）
  ├─ video-shots.vue        镜头列表（网格+批量操作+拆镜+生成详情）
  └─ video-shot-detail.vue  镜头详情（4 工作台 tab：character/storyboard/video/scene）

现有页面层（保留，作为下级跳转）
  ├─ screenplay.vue         剧本生成/查看
  ├─ shot-list.vue          旧管线镜头列表
  ├─ storyboard.vue         单镜故事版（保留，工作台也可直接操作）
  ├─ video-characters.vue   视频角色库
  └─ render-jobs.vue        渲染作业/视频播放

状态层
  ├─ stores/videoGen.ts      新增：Pinia 版 videoGenStore（发布订阅+持久化）
  └─ stores/videoWorkflow.ts 扩展：补充 regenerate/concat/reset/parse 等方法

API 层
  ├─ api/video.ts           扩展：新增 ~35 个 API 函数
  └─ api/types.ts           扩展：补充 VideoStylePreset 等类型

组合式函数层
  └─ composables/useWorkflowPolling.ts  新增：工作流状态轮询
```

### 2.2 核心数据流

```
chapter-view 第5标签 / workspace入口
  → video-workflow.vue（选择章节 → 创建/选择工作流 → 选风格+引用资产）
    → video-shots.vue（拆镜 → 生成详情 → 批量故事版 → 批量视频 → 拼接）
      → video-shot-detail.vue（4 工作台 tab：单镜操作）
        → 操作弹窗（lv-modal/action-sheet）
        → 跳转现有页面（video-characters/render-jobs）
```

### 2.3 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| UI 布局适配 | 分页面导航 | 每屏聚焦一个任务，符合移动端导航习惯 |
| 入口位置 | chapter-view 第 5 标签 + workspace 入口 | 覆盖最全，体验一致 |
| 现有页面处理 | 保留独立页面 + 新增工作台枢纽 | 充分利用现有代码，改动小 |
| 旧版功能取舍 | 只移植新版流水线 | 降低工作量，旧版在 web 端已部分废弃 |
| 架构方案 | 多页面分阶段工作台 | 页面可独立优化，渐进交付 |

---

## 三、页面结构详细设计

### 3.1 video-workflow.vue（工作流管理页）

**文件路径**：`storycanvas-mobile/src/pages/workspace/video-workflow.vue`

**职责**：工作流创建、列表展示、状态轮询、风格预设选择、引用资产选择

**布局**：
```
┌─────────────────────────────┐
│  lv-navbar "视频工作流"       │
├─────────────────────────────┤
│  章节选择器（chapter-selector）│
├─────────────────────────────┤
│  ┌─工作流卡片 1─────────────┐│
│  │ 状态徽标 + 进度条         ││
│  │ 镜头数/已完成/失败        ││
│  │ [继续] [重置] [拼接]      ││
│  └─────────────────────────┘│
│  ┌─工作流卡片 2─────────────┐│
│  │ ...                      ││
│  └─────────────────────────┘│
├─────────────────────────────┤
│  [新建工作流] lv-fab         │
└─────────────────────────────┘
```

**页面参数**：`chapterId`（可选，从 chapter-view 跳转时传入）

**功能清单**：
1. 加载章节工作流列表（`listChapterVideoWorkflows`）
2. 章节选择器切换章节
3. 工作流卡片展示：状态徽标、进度条、镜头统计、操作按钮
4. 新建工作流弹窗：
   - 风格预设选择（分类展示，`listStylePresets`）
   - 自定义风格参考图上传（`uni.chooseImage` → `uploadStyleReferenceImage`）
   - 引用资产选择（4 种预设模板：故事版+人物/仅人物/全部/自定义）
   - 视频比例选择（16:9 / 9:16）
5. 工作流操作：继续（跳转 video-shots）、重置（`resetChapterWorkflow`）、拼接（`concatChapterVideoWorkflow`）
6. 状态轮询：每 4 秒调用 `getChapterVideoWorkflowStatus`，ACTIVE_STATUSES 期间持续轮询

**状态轮询逻辑**：
```typescript
const ACTIVE_STATUSES = new Set([
  'parsing_shots', 'generating_storyboards',
  'generating_videos', 'reanalyzing_prompts', 'generating_details'
])
// 每 4 秒轮询，完成后更新 videoGenStore
```

### 3.2 video-shots.vue（镜头列表页）

**文件路径**：`storycanvas-mobile/src/pages/workspace/video-shots.vue`

**职责**：展示工作流所有镜头，支持批量操作和单镜跳转

**页面参数**：`workflowId`（必需）

**布局**：
```
┌─────────────────────────────┐
│  lv-navbar "镜头列表" + 返回  │
├─────────────────────────────┤
│  工作流状态栏（阶段+进度）    │
├─────────────────────────────┤
│  批量操作栏（粘性置顶）       │
│  [全选] [批量故事版] [批量视频]│
├─────────────────────────────┤
│  ┌─镜头卡片 1──────────────┐│
│  │ ☐ 镜头1 摘要             ││
│  │ [故事版缩略图] [视频缩略图]││
│  │ 状态标签                 ││
│  └─────────────────────────┘│
│  ┌─镜头卡片 2──────────────┐│
│  │ ...                      ││
│  └─────────────────────────┘│
├─────────────────────────────┤
│  底部操作栏                  │
│  [拆镜] [生成详情] [拼接视频] │
└─────────────────────────────┘
```

**镜头卡片内容**：
- 复选框（选中/跳过）
- 镜头序号、摘要、场景、运镜
- 故事版缩略图（有则显示图片，无则显示空状态）+ 状态标签（生成中/已就绪/失败）
- 视频缩略图（有则显示播放图标，无则显示空状态）+ 状态标签
- 点击卡片 → 跳转 `video-shot-detail.vue?workflowId=X&shotId=Y`

**批量操作**：
- 全选/反选/清除选择
- 批量生成故事版（`selectedShotIds` → `generateChapterWorkflowStoryboards`）
- 批量生成视频（`selectedShotIds` → `generateChapterWorkflowVideos`）

**底部操作**（根据工作流状态动态显示）：
- 拆镜（`parseChapterWorkflowShots`）- 无镜头时显示
- 生成详情（`generateChapterWorkflowShotDetails`）- 有镜头无详情时显示
- 拼接视频（`concatChapterVideoWorkflow`）- 所有视频就绪时显示

**状态轮询**：复用 `useWorkflowPolling` composable

### 3.3 video-shot-detail.vue（镜头详情 + 4 工作台）

**文件路径**：`storycanvas-mobile/src/pages/workspace/video-shot-detail.vue`

**职责**：单镜详情查看，4 个工作台 tab 操作

**页面参数**：`workflowId`（必需）、`shotId`（必需）

**布局**：
```
┌─────────────────────────────┐
│  lv-navbar "镜头 N" + 返回   │
├─────────────────────────────┤
│  镜头信息卡（摘要/场景/运镜/  │
│  动作/情绪/连续性）           │
├─────────────────────────────┤
│  lv-tabs [角色][场景道具]     │
│          [故事版][视频]      │
├─────────────────────────────┤
│  ← tab 内容区 →              │
│  资源预览（图片/视频）        │
│  提示词编辑器（折叠式）       │
│  引用资产选择（故事版/视频）  │
│  操作按钮组                  │
├─────────────────────────────┤
│  [跳转角色库] [跳转渲染]      │
└─────────────────────────────┘
```

**4 个工作台 tab 内容**：

| Tab | 资源预览 | 提示词编辑 | 引用资产 | 操作按钮 |
|-----|---------|-----------|---------|---------|
| 角色资产 | 角色参考图网格 | 角色提示词（character_prompts） | - | 生成/上传替换/删除/重绘 |
| 场景道具 | 场景图+道具图网格 | 场景提示词+道具提示词 | - | 生成/上传替换/删除/重绘 |
| 故事版 | 故事版图片 | 故事版提示词（storyboard_prompt） | 引用资产选择器 | 生成/上传/删除/重绘/保存提示词/重新分析 |
| 视频 | 视频播放器 | 视频提示词（video_prompt） | 引用资产选择器+视频比例 | 生成/上传/删除/重绘/保存提示词/重新分析/预览提示词 |

**操作弹窗实现**：
- 生成/重生成：直接调用 API，`videoGenStore.startJob` 驱动 loading
- 上传替换：`uni.chooseImage` → `uploadShotStoryboard`/`uploadShotVideo`/`replaceVideoAsset`
- 删除：`lv-modal` 确认 → `clearShotStoryboard`/`clearShotVideo`/`deleteVideoAsset`
- 重绘：调用 `regenerate` API（移动端不做画刷，直接整图重绘）
- 保存提示词：`saveChapterShotPrompts`
- 重新分析：`reanalyzeChapterShotPrompts` / `reanalyzeChapterWorkflowStoryboardPrompt`
- 预览提示词：`previewVideoPrompt` → `lv-modal` 展示

**引用资产选择器**（故事版/视频 tab 内）：
- 4 种预设模板：`storyboard_and_chars`（故事版+人物）、`chars_only`（仅人物）、`all`（全部）、`custom`（手动勾选）
- 分类浏览：故事版/人物/场景/道具
- 推荐资产高亮（根据镜头 characters 和 scene_location 自动匹配）

**底部跳转**：
- 跳转角色库：`uni.navigateTo({ url: '/pages/workspace/video-characters?storyId=X' })`
- 跳转渲染：`uni.navigateTo({ url: '/pages/workspace/render-jobs?shotId=Y' })`

---

## 四、状态管理设计

### 4.1 新增 stores/videoGen.ts

对标 web 端 `videoGenStore.ts`，用 Pinia 实现发布订阅 + 持久化的生成状态管理。

**状态接口**：
```typescript
interface VideoGenState {
  active: boolean           // 是否正在生成
  jobId: number | null      // 当前 job ID
  status: string            // pending/queued/running/succeeded/failed/cancelled
  progress: number          // 0-100
  statusMsg: string         // 人类可读的状态消息
  errorMsg: string          // 错误消息
  lastEventAt: number       // 最后更新时间戳
}

type AssetType = 'video' | 'storyboard' | 'character' | 'scene'
```

**存储设计**：
- 内存：`Map<string, VideoGenState>`，键格式 `<shotId>` 或 `<shotId>:<assetType>`
- 持久化：`uni.setStorageSync('video_gen_states', ...)`，H5 和小程序统一
- 过期时间：24 小时（`STATE_EXPIRY_MS = 24 * 60 * 60 * 1000`）

**Store API**：
| 方法 | 功能 |
|------|------|
| `get(shotId, type?)` | 获取指定镜头/类型的生成状态 |
| `set(shotId, state, type?)` | 设置完整状态并持久化 |
| `patch(shotId, partial, type?)` | 局部更新状态 |
| `startJob(shotId, jobId, type?)` | 设置初始生成中状态 |
| `updateProgress(shotId, status, progress, statusMsg, type?)` | 更新进度 |
| `markSucceeded(shotId, type?)` | 标记成功 |
| `markFailed(shotId, errorMsg, type?)` | 标记失败 |
| `clear(shotId, type?)` | 清除某个状态 |
| `clearAll(shotId)` | 清除指定镜头所有资产类型状态 |
| `cleanupExpired()` | 清理过期状态 |

**发布订阅**：Pinia 的 reactive 特性自动驱动，组件中 `computed(() => videoGenStore.get(shotId, 'storyboard'))` 即可响应式更新。

### 4.2 扩展 stores/videoWorkflow.ts

**补充状态**：
- `currentWorkflow: ChapterVideoWorkflow | null`
- `currentShots: ChapterVideoShot[]`
- `chapterAssets: VideoAsset[]`
- `stylePresets: VideoStylePreset[]`
- `selectedReferenceIds: number[]`
- `selectedStyle: string`
- `styleReferenceImageUrl: string | null`
- `videoAspectRatio: '16:9' | '9:16'`
- `selectedShotIds: Set<number>`
- `skippedShotIds: Set<number>`

**补充方法**：
| 方法 | 对应 API | 说明 |
|------|---------|------|
| `parseShots(workflowId)` | `parseChapterWorkflowShots` | 拆镜 |
| `generateShotDetails(workflowId, payload)` | `generateChapterWorkflowShotDetails` | 生成镜头详情 |
| `generateStoryboards(workflowId, payload)` | `generateChapterWorkflowStoryboards` | 批量生成故事版 |
| `generateVideos(workflowId, payload)` | `generateChapterWorkflowVideos` | 批量生成视频 |
| `runAllStages(workflowId)` | `runAllChapterWorkflowStages` | 全自动执行 |
| `regenerateStoryboard(shotId, promptOverride?, refAssetIds?)` | `regenerateChapterWorkflowStoryboard` | 重生成故事版 |
| `regenerateVideo(shotId, promptOverride?, refAssetIds?, aspectRatio?)` | `regenerateChapterWorkflowVideo` | 重生成视频 |
| `reanalyzePrompt(shotId)` | `reanalyzeChapterShotPrompts` | 重新分析提示词 |
| `reanalyzeStoryboardPrompt(workflowId, payload)` | `reanalyzeChapterWorkflowStoryboardPrompt` | 重新分析故事版提示词 |
| `concatVideo(workflowId)` | `concatChapterVideoWorkflow` | 拼接视频 |
| `resetWorkflow(workflowId)` | `resetChapterWorkflow` | 重置工作流 |
| `clearShotStoryboard(shotId)` | `clearShotStoryboard` | 清除故事版 |
| `clearShotVideo(shotId)` | `clearShotVideo` | 清除视频 |
| `saveShotPrompts(shotId, prompts)` | `saveChapterShotPrompts` | 保存提示词 |
| `previewVideoPrompt(shotId, refAssetIds?, promptOverride?)` | `previewVideoPrompt` | 预览视频提示词 |
| `loadStylePresets()` | `listStylePresets` | 加载风格预设 |
| `uploadStyleReferenceImage(workflowId, file)` | `uploadStyleReferenceImage` | 上传风格参考图 |
| `loadChapterAssets(chapterId)` | `listVideoAssets` | 加载章节资产 |

---

## 五、API 层补全

### 5.1 新增 API 函数清单（~35 个）

**工作流阶段 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `parseChapterWorkflowShots(workflowId)` | `POST /api/video/chapter-workflows/:id/shots/parse` | 拆镜 |
| `generateChapterWorkflowShotDetails(workflowId, payload)` | `POST /api/video/chapter-workflows/:id/shots/generate-details` | 生成镜头详情 |
| `generateChapterWorkflowStoryboards(workflowId, payload)` | `POST /api/video/chapter-workflows/:id/storyboards/generate` | 批量生成故事版 |
| `generateChapterWorkflowVideos(workflowId, payload)` | `POST /api/video/chapter-workflows/:id/videos/generate` | 批量生成视频 |
| `runAllChapterWorkflowStages(workflowId)` | `POST /api/video/chapter-workflows/:id/run-all` | 全自动执行 |
| `reanalyzeChapterWorkflowStoryboardPrompt(workflowId, payload)` | `POST /api/video/chapter-workflows/:id/reanalyze` | 重新分析故事版提示词 |
| `reanalyzeChapterShotPrompts(shotId)` | `POST /api/video/chapter-workflows/shots/:id/reanalyze` | 单镜头重新分析 |
| `previewVideoPrompt(shotId, refAssetIds?, promptOverride?)` | `POST /api/video/chapter-workflows/shots/:id/preview-prompt` | 预览视频提示词 |
| `resetChapterWorkflow(workflowId)` | `POST /api/video/chapter-workflows/:id/reset` | 重置工作流 |
| `getChapterVideoWorkflowStatus(workflowId)` | `GET /api/video/chapter-workflows/:id/status` | 获取工作流状态 |

**镜头操作 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `clearShotStoryboard(shotId)` | `DELETE /api/video/chapter-workflows/shots/:id/storyboard` | 清除故事版 |
| `clearShotVideo(shotId)` | `DELETE /api/video/chapter-workflows/shots/:id/video` | 清除视频 |
| `saveChapterShotPrompts(shotId, prompts)` | `PUT /api/video/chapter-workflows/shots/:id/prompts` | 保存提示词 |

**资产生成 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `generateShotCharacterAsset(shotId, payload)` | `POST /api/shots/:id/assets/character/generate` | 生成角色资产 |
| `generateShotPropAsset(shotId, payload)` | `POST /api/shots/:id/assets/prop/generate` | 生成道具资产 |
| `generateShotSceneAsset(shotId, payload)` | `POST /api/shots/:id/assets/scene/generate` | 生成场景资产 |
| `renderStoryboardFrame(shotId, payload)` | `POST /api/shots/:id/storyboard/render` | 渲染分镜图 |

**角色库 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `listVideoCharacters(storyId)` | `GET /api/stories/:id/video-characters-v2` | 列出角色库 |
| `generateVideoCharacters(storyId)` | `POST /api/stories/:id/video-characters-v2/generate` | 生成角色库 |
| `createCharacterVersion(...)` | `POST /api/video-characters/:id/versions` | 创建角色版本 |
| `deleteCharacterVersion(...)` | `DELETE /api/video-characters/versions/:id` | 删除角色版本 |
| `generateCharacterRefImage(...)` | `POST /api/video-characters/:id/ref-image/generate` | 生成角色参考图 |
| `deleteVideoCharacterRefImage(...)` | `DELETE /api/video-characters/ref-images/:id` | 删除角色参考图 |
| `redrawCharacterRefImage(...)` | `POST /api/video-characters/ref-images/:id/redraw` | 重绘角色参考图 |

**视频任务 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `retryVideoJob(jobId, payload?)` | `POST /api/video/jobs/:id/retry` | 重试任务 |
| `listShotClips(shotId)` | `GET /api/shots/:id/clips` | 列出片段 |
| `activateShotClip(shotId, clipId)` | `POST /api/shots/:id/clips/:clipId/activate` | 激活片段 |

**资产管理 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `listVideoAssets(chapterId, assetType?)` | `GET /api/chapters/:id/video-assets` | 列出视频资产 |
| `createVideoAsset(chapterId, payload)` | `POST /api/chapters/:id/video-assets` | 创建视频资产 |
| `deleteVideoAsset(assetId)` | `DELETE /api/video-assets/:id` | 删除视频资产 |
| `getShotStoryboards(shotId)` | `GET /api/shots/:id/storyboards` | 获取分镜图 |

**风格预设 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `listStylePresets()` | `GET /api/video/style-presets` | 列出风格预设 |
| `uploadStyleReferenceImage(workflowId, file)` | `POST /api/video/chapter-workflows/:id/style-reference` | 上传风格参考图 |

**上传/替换 API**：
| 函数 | 端点 | 说明 |
|------|------|------|
| `uploadShotStoryboard(shotId, file)` | `POST /api/video/chapter-workflows/shots/:id/storyboard/upload` | 上传故事版 |
| `uploadShotVideo(shotId, file)` | `POST /api/video/chapter-workflows/shots/:id/video/upload` | 上传视频 |
| `replaceVideoAsset(assetId, file)` | `POST /api/video-assets/:id/replace` | 替换资产图 |
| `regenerateVideoAsset(assetId, prompt?, mask?)` | `POST /api/video-assets/:id/regenerate` | 重绘资产图 |

### 5.2 类型补充

新增到 `storycanvas-mobile/src/api/types.ts`：

```typescript
/** 视频风格预设 */
export interface VideoStylePreset {
  id: number
  name: string
  category: string
  description?: string | null
  reference_image_url?: string | null
  is_active: boolean
  sort_order: number
}

/** 镜头首尾帧响应 */
export interface ShotFramesResponse {
  shot_id: number
  first_frame_url?: string | null
  last_frame_url?: string | null
}

/** 已渲染片段 */
export interface RenderedClip {
  id: number
  shot_id: number
  clip_url: string
  duration_seconds: number
  is_active: boolean
  created_at: string
}

/** 视频角色版本 */
export interface CharacterVersion {
  id: number
  label: string
  is_default: boolean
  ref_asset_id?: number | null
  ref_asset_url?: string | null
  appearance_card: string
  sort_order: number
}

/** 视频角色（角色库版本） */
export interface VideoCharacter {
  id: number
  story_id: number
  name: string
  versions: CharacterVersion[]
}

/** 提示词草稿 */
export interface ShotAssetPromptDraft {
  shot_id: number
  storyboard_prompt?: string | null
  video_prompt?: string | null
  character_prompts?: Array<{ name: string; prompt: string }> | null
  scene_prompt?: string | null
  prop_prompts?: Array<{ name: string; prompt: string }> | null
}
```

---

## 六、入口集成

### 6.1 chapter-view.vue 第 5 标签

修改 `storycanvas-mobile/src/pages/workspace/chapter-view.vue`：

```vue
<!-- 修改 tabs 数组，将「视频」插入第 4 位，「助手」移到第 5 位 -->
<lv-swiper-tabs
  :tabs="['框架', '编辑', '漫画', '视频', '助手']"
  v-model:current="activeTabIndex"
>
  <!-- 视频标签（新增 #tab-3） -->
  <template #tab-3>
    <scroll-view scroll-y class="chapter-view__tab-scroll">
      <view class="chapter-view__tab">
        <!-- 视频工作流入口卡 -->
        <view class="video-entry-card" @tap="goToVideoWorkflow">
          <lv-icon name="Video" :size="40" color="#2563eb" />
          <view class="video-entry-card__body">
            <text class="video-entry-card__title">视频工作流</text>
            <text class="video-entry-card__desc">创建视频工作流，AI 自动拆镜生成分镜视频</text>
          </view>
          <lv-icon name="ChevronRight" :size="20" color="#94a3b8" />
        </view>

        <!-- 已有工作流快捷入口（如有） -->
        <view v-if="existingWorkflows.length > 0" class="video-workflow-list">
          <view v-for="wf in existingWorkflows" :key="wf.id" class="video-workflow-item"
                @tap="goToVideoShots(wf.id)">
            <text class="video-workflow-item__title">工作流 #{{ wf.id }}</text>
            <text class="video-workflow-item__status">{{ wf.workflow_status }}</text>
          </view>
        </view>
      </view>
    </scroll-view>
  </template>

  <!-- 助手标签改为 #tab-4 -->
  <template #tab-4>
    <!-- 原助手内容不变 -->
  </template>
</lv-swiper-tabs>
```

**跳转逻辑**：
```typescript
function goToVideoWorkflow() {
  const chapterId = workspaceStore.activeChapterId
  uni.navigateTo({ url: `/pages/workspace/video-workflow?chapterId=${chapterId}` })
}

function goToVideoShots(workflowId: number) {
  uni.navigateTo({ url: `/pages/workspace/video-shots?workflowId=${workflowId}` })
}
```

### 6.2 workspace/index.vue 入口

修改 `storycanvas-mobile/src/pages/workspace/index.vue`，在创作中心页面增加"视频创作"卡片：

```vue
<view class="workspace-entry-video" @tap="goToVideoWorkflow">
  <lv-icon name="Video" :size="32" color="#2563eb" />
  <text>视频创作</text>
  <text class="workspace-entry-video__desc">从章节创建视频工作流</text>
</view>
```

### 6.3 pages.json 注册新页面

在 `storycanvas-mobile/src/pages.json` 的 `pages/workspace` 分包中注册 3 个新页面：

```json
{
  "path": "pages/workspace/video-workflow",
  "style": { "navigationBarTitleText": "视频工作流" }
},
{
  "path": "pages/workspace/video-shots",
  "style": { "navigationBarTitleText": "镜头列表" }
},
{
  "path": "pages/workspace/video-shot-detail",
  "style": { "navigationBarTitleText": "镜头详情" }
}
```

---

## 七、组合式函数设计

### 7.1 composables/useWorkflowPolling.ts（新增）

工作流状态轮询 composable，对标 web 端 `pollWorkflowUntilSettled`。

```typescript
import { ref, onMounted, onUnmounted, type Ref } from 'vue'
import { videoApi } from '@/api'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useVideoGenStore } from '@/stores/videoGen'

const ACTIVE_STATUSES = new Set([
  'parsing_shots', 'generating_storyboards',
  'generating_videos', 'reanalyzing_prompts', 'generating_details'
])

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

      if (ACTIVE_STATUSES.has(status.workflow_status)) {
        timerRef.value = setTimeout(tick, 4000)
        return
      }

      // 完成：更新 videoGenStore
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
    } catch (error: any) {
      console.error('工作流轮询失败:', error)
    } finally {
      isPolling.value = false
    }
  }

  function start() {
    if (workflowId.value && !timerRef.value) tick()
  }

  function stop() {
    if (timerRef.value) {
      clearTimeout(timerRef.value)
      timerRef.value = null
    }
    isPolling.value = false
  }

  onMounted(start)
  onUnmounted(stop)

  return { isPolling, start, stop }
}
```

---

## 八、工作台操作矩阵

完整对标 web 端 `VideoCardWorkbench` 的 4 类型 x 6+ 操作：

| 操作 | character | scene | storyboard | video |
|------|-----------|-------|------------|-------|
| 生成/重生成 | `regenerateVideoAsset` | `regenerateVideoAsset` | `regenerateChapterWorkflowStoryboard` | `regenerateChapterWorkflowVideo` |
| 上传替换 | `replaceVideoAsset` | `replaceVideoAsset` | `uploadShotStoryboard` | `uploadShotVideo` |
| 删除 | `deleteVideoAsset` | `deleteVideoAsset` | `clearShotStoryboard` | `clearShotVideo` |
| 重绘 | `regenerateVideoAsset` | `regenerateVideoAsset` | `regenerateChapterWorkflowStoryboard` | `regenerateChapterWorkflowVideo` |
| 保存提示词 | `saveChapterShotPrompts` | `saveChapterShotPrompts` | `saveChapterShotPrompts` | `saveChapterShotPrompts` |
| 重新分析 | `reanalyzeChapterShotPrompts` | `reanalyzeChapterShotPrompts` | `reanalyzeChapterWorkflowStoryboardPrompt` | `reanalyzeChapterWorkflowStoryboardPrompt` |
| 预览提示词 | - | - | - | `previewVideoPrompt` |
| 引用资产选择 | - | - | 支持 | 支持 |
| 视频比例选择 | - | - | - | 支持 |

**移动端简化项**：
- 重绘操作改为整图重绘（不传 mask），调用 regenerate API
- 首尾帧生成（`ShotFrameRegenerationModal`）不移植（属于旧版功能）

---

## 九、错误处理

| 场景 | 处理方式 |
|------|---------|
| API 调用错误 | `uni.showToast({ title: e.message || '操作失败', icon: 'none' })` |
| 工作流失败 | 轮询检测到 `failed` 状态 → `videoGenStore.markFailed` → UI 显示错误信息 + 重试按钮 |
| 网络超时 | `request.ts` 已有 30 秒超时 + 401 自动跳转登录 |
| 取消操作 | `videoGenStore.clear` 清除状态，UI 恢复初始 |
| 重复提交 | 操作按钮 `:loading` 状态禁用 |
| 页面参数缺失 | `lv-empty` 提示"参数错误" |
| 工作流不存在 | `lv-empty` 提示"未找到工作流" |

---

## 十、测试策略

| 测试类型 | 工具/方法 | 覆盖范围 |
|---------|----------|---------|
| 类型检查 | `npm run type-check`（vue-tsc --noEmit） | 所有新增/修改文件 |
| LSP 诊断 | `lsp_diagnostics` | 每个修改的文件 |
| 单元测试 | 手动验证 videoGenStore 状态管理逻辑 | startJob/markSucceeded/markFailed/cleanupExpired |
| 集成测试 | 手动验证工作流创建 → 拆镜 → 生成 | 完整流程 mock |
| 手动 QA | H5 端实际运行 | 完整工作流：创建 → 拆镜 → 故事版 → 视频 → 拼接 |
| 构建验证 | `npm run build:h5` | 生产构建无错误 |

---

## 十一、移植阶段划分

### 阶段一：核心流程（预计工作量最大）

**目标**：实现工作流创建 → 拆镜 → 批量生成 → 拼接的完整流程

**交付物**：
1. API 层补全（~35 个新函数）
2. 类型补充（`VideoStylePreset` 等）
3. `stores/videoGen.ts`（新增 Pinia store）
4. `stores/videoWorkflow.ts`（扩展方法）
5. `composables/useWorkflowPolling.ts`（新增轮询 composable）
6. `pages/workspace/video-workflow.vue`（工作流管理页）
7. `pages/workspace/video-shots.vue`（镜头列表页）
8. `chapter-view.vue` 第 5 标签入口
9. `workspace/index.vue` 视频创作入口
10. `pages.json` 注册新页面

**验证**：能在 H5 端完成 创建工作流 → 拆镜 → 生成详情 → 批量故事版 → 批量视频 → 拼接 的完整流程。

### 阶段二：工作台完整

**目标**：实现 4 个工作台 tab 的全部操作

**交付物**：
1. `pages/workspace/video-shot-detail.vue`（镜头详情页）
2. 4 个工作台 tab 的完整实现
3. 所有工作台操作（生成/上传/删除/重绘/保存提示词/重新分析/预览）
4. 引用资产选择器组件
5. 风格预设选择弹窗
6. 提示词编辑器组件

**验证**：能在镜头详情页完成所有单镜操作。

### 阶段三：增强功能

**目标**：完善角色库、资产管理、与现有页面的联动

**交付物**：
1. 角色库版本管理集成（`createCharacterVersion`/`deleteCharacterVersion`）
2. 角色参考图生成/重绘（`generateCharacterRefImage`/`redrawCharacterRefImage`）
3. 视频任务重试/片段管理（`retryVideoJob`/`listShotClips`/`activateShotClip`）
4. 资产管理面板（`listVideoAssets`/`createVideoAsset`/`deleteVideoAsset`）
5. 与现有页面的跳转联动（`video-characters.vue`/`render-jobs.vue`）
6. `videoGenStore` 过期清理定时任务

**验证**：所有功能完整，与现有页面无缝联动。

---

## 十二、文件清单

### 新增文件

| 文件路径 | 类型 | 说明 |
|---------|------|------|
| `storycanvas-mobile/src/pages/workspace/video-workflow.vue` | 页面 | 工作流管理页 |
| `storycanvas-mobile/src/pages/workspace/video-shots.vue` | 页面 | 镜头列表页 |
| `storycanvas-mobile/src/pages/workspace/video-shot-detail.vue` | 页面 | 镜头详情页（4 工作台） |
| `storycanvas-mobile/src/stores/videoGen.ts` | Store | 生成状态管理（Pinia 版 videoGenStore） |
| `storycanvas-mobile/src/composables/useWorkflowPolling.ts` | Composable | 工作流状态轮询 |
| `storycanvas-mobile/src/components/asset-reference-selector/asset-reference-selector.vue` | 组件 | 引用资产选择器 |
| `storycanvas-mobile/src/components/style-selector-modal/style-selector-modal.vue` | 组件 | 风格预设选择弹窗 |
| `storycanvas-mobile/src/components/shot-prompt-editor/shot-prompt-editor.vue` | 组件 | 提示词编辑器 |

### 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `storycanvas-mobile/src/api/video.ts` | 新增 ~35 个 API 函数 |
| `storycanvas-mobile/src/api/types.ts` | 新增 `VideoStylePreset` 等类型 |
| `storycanvas-mobile/src/stores/videoWorkflow.ts` | 扩展状态和方法 |
| `storycanvas-mobile/src/pages/workspace/chapter-view.vue` | 新增第 5 标签「视频」 |
| `storycanvas-mobile/src/pages/workspace/index.vue` | 新增视频创作入口 |
| `storycanvas-mobile/src/pages.json` | 注册 3 个新页面 |

---

## 十三、风险与注意事项

1. **uni-app 平台差异**：H5 和小程序的 `uni.chooseImage`、`uni.navigateTo` 行为一致，但文件上传在小程序端需要 `uni.uploadFile` 而非 `fetch`。现有 `request.ts` 已处理，但上传 API 需要确认是否需要单独封装。

2. **轮询性能**：每 4 秒轮询在移动端可能影响电量，建议在页面 `onHide` 时暂停轮询，`onShow` 时恢复。

3. **Set 响应式**：Pinia 中 `Set<number>` 类型的响应式需要用 `reactive` 包裹或改用 `number[]`。建议 `selectedShotIds` 和 `skippedShotIds` 用 `number[]` 实现。

4. **视频播放**：uni-app 的 `<video>` 组件在 H5 和小程序行为有差异，需要测试兼容性。

5. **图片上传格式**：`uni.chooseImage` 返回临时路径，需要通过 `uni.uploadFile` 上传到后端，不能直接用 `fetch`。

6. **后端 API 端点确认**：部分 API 端点路径需要与后端实际路由核对，确保路径正确。

7. **videoGenStore 持久化**：`uni.setStorageSync` 有存储大小限制（小程序 10MB），需要控制状态数据大小，定期清理过期状态。
