# 视频工作流工作台重设计

**日期**: 2026-06-07
**项目**: Manwen-Studio (LoreVista)
**状态**: 设计已确认，待实施

---

## 1. 概述

### 1.1 目标

重新设计视频工作台，简化视频创作流程。核心变化：
- 移除左侧小说框架区，替换为可收起的章节选择列表
- 跳过影视剧本/场次中间层，章节直接一键拆分为分镜
- 分镜列表分页展示，每行内联展示资产卡片（人物/场景/首尾帧）
- 生成的资产图可点击放大进入二级重绘工作台（整图/局部重绘）
- 支持资产继承（章节内 + 跨章节）
- 画面生成和视频生成支持参考资产勾选

### 1.2 设计原则

- **漫画工作台零影响**：`WorkspaceLayout`、`MangaPanel` 保持完整不变
- **复用优先**：`ImageRedrawModal` 提取为共享组件，API 层大量复用
- **简洁流程**：章节 → 分镜 → 资产 → 视频，四步直达
- **容错健壮**：150s 超时 / 3次重试 / 部分失败可单独重试

---

## 2. 架构方案

采用**混合方案（方案 C）**：新建布局组件 + 充分复用底层模块。

### 2.1 组件树

```
WorkspacePage (不变，仅切换模式)
  └── VideoStoryboardLayout ★新建★ (替代 VideoWorkspaceLayout)
        ├── ChapterListPanel ★新建★ (左侧，可收起/展开)
        │     ├── 收起/展开按钮
        │     ├── 章节列表项 (序号 + 标题 + 分镜进度状态)
        │     └── 当前选中章节高亮
        │
        └── 主工作区 (flex-1)
              ├── 顶部工具栏
              │     ├── 全选复选框
              │     ├── "一键分镜" 按钮
              │     ├── "批量分析提示词" 按钮 (仅对勾选分镜执行)
              │     └── "批量生成首尾帧" 按钮 (仅对勾选分镜执行)
              │
              └── VideoStoryboardPanel ★新建★
                    ├── 顶部分页控件
                    ├── VideoShotRow × N (每页固定条数)
                    │     ├── ☑ 勾选复选框
                    │     ├── 分镜信息区 (序号/标题/描述/镜头类型)
                    │     ├── 资产紧凑卡片区
                    │     │     ├── 人物卡片 × N (缩略图 + 角色名)
                    │     │     ├── 场景卡片 × 1 (缩略图)
                    │     │     └── 首尾帧卡片 × 2 (首帧/尾帧)
                    │     ├── 参考资产选择按钮 → AssetReferenceSelector 弹窗
                    │     └── 生成视频按钮
                    └── 底部分页控件
```

### 2.2 共享组件提取

```
MangaPanel.tsx (内部 ImageRedrawModal)
         ↓ 提取
components/shared/ImageRedrawModal.tsx
  ├── 导出: ImageRedrawModal 组件
  ├── 导出: ImageEditTarget, ImageRedrawMode 类型
  ├── 功能: 整图重绘 + 局部重绘 (Canvas 涂抹蒙版)
  └── 缩放: 100% / 135% / 170%

MangaPanel.tsx → import { ImageRedrawModal } from './shared/ImageRedrawModal'
VideoStoryboardPanel → import { ImageRedrawModal } from '../shared/ImageRedrawModal'
```

---

## 3. 文件改动清单

```
frontend/src/
├── components/
│   ├── shared/
│   │   └── ImageRedrawModal.tsx    ★新建★ 从 MangaPanel 提取
│   │
│   ├── VideoStoryboardLayout.tsx   ★新建★ 主布局
│   ├── ChapterListPanel.tsx        ★新建★ 可收起章节列表 (信息版)
│   ├── VideoStoryboardPanel.tsx    ★新建★ 分页分镜列表 + 工具栏
│   ├── AssetReferenceSelector.tsx  ★新建★ 参考资产选择弹窗
│   │
│   ├── WorkspacePage.tsx           ✎修改  video 模式路由到新组件
│   ├── MangaPanel.tsx              ✎修改  ImageRedrawModal 改为共享导入
│   │
│   ├── VideoWorkspaceLayout.tsx    保留   不删除，作回退参考
│   ├── StoryboardPanel.tsx         保留   场景级分镜，不用于新流程
│   └── ShotAssetWorkflowPanel.tsx  保留   逻辑参考
│
└── api.ts                          ✎修改  新增章节分镜生成 API
```

---

## 4. 数据流

### 4.1 核心流程

```
选择章节 → 一键分镜 → 批量分析提示词 → 按需生成首尾帧 → 选择参考资产 → 生成视频
```

### 4.2 各步骤详情

#### Step 1: 选择章节
```
ChapterListPanel → onChapterSelect(chapter)
  ├── GET /api/chapters/{id}/shots (加载已有分镜数据)
  ├── 如有已保存分镜 → 渲染分镜列表
  └── 如无数据 → 显示空状态引导 "点击「一键分镜」开始"
```

#### Step 2: 一键分镜 (拆分 + 资产识别)
```
点击 "一键分镜"
  ├── POST /api/chapters/{chapter_id}/storyboard/generate ★新 API★
  │     请求: { shot_count_hint?, style_preset? }
  │     响应: { shots: VideoShot[], total_count: number }
  │     每镜已含 AI 分析: character_involvement, scene_mood, title, action_description
  ├── 渲染分页分镜列表
  └── 超时: 150s, 重试: 3次
```

#### Step 3: 批量分析提示词 (仅选中分镜)
```
勾选目标分镜 → 点击 "批量分析提示词"
  ├── 对每镜: POST /api/video/shots/{id}/prompts/parse (复用)
  │     返回: ShotAssetPromptDraft {
  │       character_prompts, storyboard_prompt,
  │       first_frame_prompt, last_frame_prompt, video_prompt
  │     }
  ├── 更新每行资产提示词显示
  └── 前端 3 并发调度
```

#### Step 4: 按需生成首尾帧
```
勾选目标分镜 → 点击 "批量生成首尾帧"
  ├── 对每镜: POST /api/video/shots/{id}/frames/generate (复用)
  │     参数: {
  │       frame_type: "both",
  │       inherit_character_assets: true,   // 章节内继承
  │       inherit_scene_assets: true,
  │       inherit_storyboard_asset: true,
  │       reference_asset_ids: [...]         // 跨章节继承 (来自角色库)
  │     }
  │     返回: ShotFramesResponse { first_frames, last_frames }
  ├── 资产缩略图即时更新在分镜行中
  └── 前端 3 并发调度
```

#### Step 5: 选择参考资产 → 生成视频
```
分镜行末尾: [参考资产] [生成视频]
  ├── 点击 [参考资产] → AssetReferenceSelector 弹窗
  │     ├── 预设模板: "仅首帧" / "首帧+人物" / "全部资产" / "自定义"
  │     ├── 可用资产列表 (本章已生成 + 角色库)，可多选
  │     └── 确认后关联到当前分镜
  │
  └── 点击 [生成视频]:
        POST /api/video/shots/{id}/render (复用)
        参数: { reference_asset_ids: [...] }
        超时: 150s, 重试: 3次
```

#### Step 6: 资产图放大 → 二级重绘工作台
```
资产缩略图 onClick → 打开 ImageRedrawModal (共享组件)
  ├── 整图重绘: 修改提示词 → 提交
  └── 局部重绘: Canvas 涂抹蒙版 → 提交
  POST /api/video/shots/{id}/frames/regenerate (复用)
  完成后 → 刷新该镜资产 → 更新缩略图
```

### 4.3 资产继承链路

```
章节内继承 (inherit_* 参数):
  分镜1 → 生成角色A图、场景图
       ↓
  分镜2 → reference_asset_ids 自动包含分镜1的同角色/同场景资产
       ↓
  分镜3 → reference_asset_ids 自动包含分镜1和2的资产

跨章节继承 (全局角色库):
  第1章 生成角色A图 → 存入角色库 (VideoCharacterLibrary)
  第5章 同名角色A → 从角色库自动匹配 → reference_asset_ids 自动填充
```

---

## 5. 状态管理

`VideoStoryboardLayout` 作为状态容器：

```
state:
  chapters: Chapter[]              (章节列表)
  selectedChapter: Chapter | null  (当前选中章节)
  leftCollapsed: boolean           (左侧章节列表收起状态)
  shots: VideoShot[]               (当前章节的分镜列表)
  checkedShotIds: Set<number>      (勾选的分镜 ID 集合，跨页保留)
  shotsPage: number                (当前页码)
  shotsPerPage: number             (每页条数, 默认 10)
  shotsLoading: boolean            (分镜加载中)
  generatingStoryboard: boolean    (一键分镜中)
  analyzingPrompts: Set<number>    (正在分析提示词的分镜 ID)
  generatingFrames: Set<number>    (正在生成首尾帧的分镜 ID)
  chapterAssets: VideoAsset[]      (本章已生成资产，用于继承)
  globalCharacters: VideoCharacter[] (全局角色库，用于跨章继承)
```

---

## 6. API 接口

### 6.1 新增 API

```
POST /api/chapters/{chapter_id}/storyboard/generate
  请求: { shot_count_hint?: number, style_preset?: string }
  响应: { shots: VideoShot[], total_count: number }
  说明: 将整个章节拆分为分镜，AI 分析每镜出场人物/场景
```

### 6.2 复用 API

| API | 用途 |
|-----|------|
| `parseShotPrompts(shotId)` | 分析提示词 |
| `generateShotFrames(shotId, payload)` | 生成首尾帧 |
| `generateShotCharacterAsset(shotId, payload)` | 生成角色资产图 |
| `renderShotVideo(shotId, payload)` | 生成视频 |
| `regenerateShotFrame(shotId, payload)` | 图片重绘 |
| `deleteVideoAsset(assetId)` | 删除资产 |
| `getShotFrames(shotId)` | 获取已有帧 |
| `listVideoAssets(params)` | 参考资产选择器数据源 |
| `getShotStoryboards(shotId)` | 获取分镜图资产 |

### 6.3 超时与重试

```
全局请求配置:
  timeout: 150_000           // 150秒
  maxRetries: 3              // 最多重试 3 次
  retryDelay: 2s → 4s → 6s  // 递增延迟
  retryOn: [ETIMEDOUT, ECONNRESET, 502, 503, 504]

批量并发控制:
  maxConcurrency: 3          // 同时最多 3 个请求
```

---

## 7. 错误处理

### 7.1 空状态

| 场景 | 提示 |
|------|------|
| 无章节 | "暂无章节，请先在编辑器中创建章节内容" |
| 已选章节，未生成分镜 | "点击顶部「一键分镜」将本章拆分为分镜" |
| 章节正文为空 | "章节内容为空，无法生成分镜" |
| 分镜仅一页 | 不显示分页控件 |

### 7.2 错误提示

| 场景 | 处理 |
|------|------|
| API 失败 | 顶栏 error banner + 错误信息 + 关闭/重试 |
| 配额不足 (402) | "本月配额已用尽，请升级套餐" + 升级链接 |
| 部分批量失败 | toast "12/15 成功，3 个失败" + 失败行标红可单独重试 |
| 第 3 次重试仍失败 | 该行标红 "生成失败: 上游服务超时，已重试 3 次" |
| 图片加载失败 | 占位图标替代缩略图 |

### 7.3 操作防护

- 异步操作期间按钮 disabled，防止重复点击
- 删除分镜前二次确认
- 局部重绘未涂抹蒙版 → toast 阻止提交
- 切换章节 → 清除分镜列表、页码归 1、清空勾选

---

## 8. 资产卡片操作

每张资产缩略图支持四个操作：

| 操作 | 行为 | API |
|------|------|------|
| 👁 查看 | 全屏预览大图 | 本地渲染 |
| ✏️ 重绘 | 打开 `ImageRedrawModal` 二级工作台 | `regenerateShotFrame` |
| 🗑 删除 | 二次确认后删除 | `deleteVideoAsset` |
| 📁 替换 | 文件选择器 → 上传本地图片替换 | 上传接口 |

删除确认弹窗文案："确认删除该资产？此操作不可撤销"
上传限制：png / jpg / webp 格式

---

## 9. 边界情况

- **跨页勾选**：切换分页保留已勾选的分镜 ID，工具栏显示「已选 X 镜」
- **分页切换**：页码输入框限制有效范围
- **章节切换**：状态完全重置
- **并发冲突**：同一分镜不允许同时执行多个资产生成操作
- **继承缺失**：如果父级资产已被删除，该引用自动跳过，不影响后续生成

---

## 10. 与原系统的兼容

- **漫画工作台**：`WorkspaceLayout` + `MangaPanel` 完全不变
- **MangaPanel 改动量**：仅将 `ImageRedrawModal` import 来源从内部定义改为 `./shared/ImageRedrawModal`，功能和样式不变
- **现有视频工作台**：`VideoWorkspaceLayout` 保留不删除，代码可作回退参考
- **API 层**：新增 1 个端点，其余全部复用现有 API
- **路由**：不变，仍通过 `WorkspacePage` 的 `workspaceMode` 切换
