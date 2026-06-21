# 移动端漫画工作台对齐 Web 端 — 设计文档

## 概述

将移动端（storycanvas-mobile/）的漫画工作台功能对齐到 Web 端水平。Web 端 MangaPanel.tsx（2820 行）功能密度远高于移动端。

## 子项目分解 & 实施顺序

### A. 漫画设置增强（比例选择 + 风格预设）

**优先级**：P0（基础 UX 提升）

**改动文件**：
- `storycanvas-mobile/src/pages/workspace/manga.vue`
- `storycanvas-mobile/src/pages/workspace/chapter-view.vue`（漫画 tab）
- `storycanvas-mobile/src/stores/manga.ts`
- `storycanvas-mobile/src/api/manga.ts`
- 可选新建 `components/style-selector/style-selector.vue`

**实现要点**：

#### A1. 比例选择器
- 新增 `aspectRatio` store state（默认 `'9:16'`）
- picker 组件，选项同 Web：9:16 / 3:4 / 2:3 / 1:1 / 3:2 / 4:3 / 16:9
- 保存在本地（`uni.setStorageSync`）+ 章节级 API
- `startMangaGeneration()` 传 `size` 参数给 SSE（`generateMangaStream` 支持 `body.size`）
- `regenerateImage()` 传 `size` 给单张重绘

#### A2. 风格预设选择器
- 新增 `components/style-selector/style-selector.vue` 弹窗组件
- 从 `adminApi.listStylePresets()` 获取预设列表
- 网格式卡片布局：名称 + 分类标签（写实/动漫/艺术/电影）
- 选中高亮，单选
- 外部传入 `presets` prop，`v-model:selectedName` 双向绑定

#### A3. 风格参考图上传
- 在风格选择区添加"上传参考图"按钮
- 调用图片选择器 → 上传 `uploadStyleReferenceImage()` API
- 成功后显示缩略图，可清除（`styleReferenceImageUrl`）

#### A4. 参数传递
- `startMangaGeneration(mode, params)` 新增 `{size, stylePresetName, styleRefUrl}`
- `regenerateImage()` 新增 `options?: {size, stylePresetName, styleRefUrl}`
- 后端 API `regenerate-image/{n}` 已支持这些参数

---

### B. 分镜脚本编辑增强

**优先级**：P1

**改动文件**：
- `storycanvas-mobile/src/pages/workspace/manga.vue`
- `storycanvas-mobile/src/pages/workspace/chapter-view.vue`
- `storycanvas-mobile/src/stores/manga.ts`

**实现要点**：

#### B1. 行内编辑
- 每行分镜右侧加铅笔图标（`Pencil` 组件）
- 点击后替换文本为 textarea，显示"保存"/"取消"按钮
- 保存更新本地 store 中的 scenes
- 顶部/底部加"保存修改"按钮 → 调 `updateScenes()` API 批量保存

#### B2. 降敏标记
- 读取 `sanitizedIndices`，对应分镜显示"已自动降敏"标签
- 降敏行加样式区分（背景色/边框）

---

### C. 角色参考图独立管理

**优先级**：P1（可并行实现）

**改动文件**：
- `storycanvas-mobile/src/pages/workspace/manga.vue` / `chapter-view.vue`
- 新建 `components/character-ref-section/character-ref-section.vue`

**实现要点**：

#### C1. 解析角色列表
- 复用 `character-profiles` 的角色解析逻辑
- 解析出角色名列表，每个角色独立区域展示

#### C2. 每角色操作
- 上传参考图：调 `uploadCharacterRefImage(storyId, charName, base64, replace?)`
- AI 生成：接 SSE `characterRefImagesUrl()` 端点
- 删除：调 `deleteCharacterRefImage(storyId, filename)`
- 预览：简单弹窗展示图片

#### C3. 垫图来源标注
- 标注"故事级全局"或"本话自定义"

---

### D. ImageRedrawModal 重绘弹窗

**优先级**：P2

**改动文件**：
- 新建 `components/image-redraw-modal/image-redraw-modal.vue`
- `storycanvas-mobile/src/pages/workspace/manga-gallery.vue`
- `storycanvas-mobile/src/pages/workspace/manga.vue`

**实现要点**：
- 弹窗显示：原图预览 + 提示词 textarea + 重绘模式选择
- 模式："整图重绘"（`regenerate`）/ "局部重绘"（`inpaint`）
- 局部重绘需 Canvas 画笔组件（移动端触摸绘制蒙版），复杂度较高
- prompt 可编辑后提交 `regenerateImage()` API

---

## 数据流

```
用户操作（比例/风格/参考图选择）
    ↓
manga store 更新 state
    ↓
startMangaGeneration() → SSE 请求体携带参数
    ↓
后端根据参数生成图片 → SSE 推送结果
    ↓
store 更新 images/scenes → UI 渲染

单张重绘：
manga store → regenerateImage(chapterId, imageNumber, prompt, options)
    ↓
API POST /api/chapters/{id}/regenerate-image/{n}
    ↓
返回新图片 → 替换列表中的对应项
```

## 未包含的范围（因复杂度高或移动端限制）

- **局部重绘（画笔蒙版）**：D 子项目中预留模式选择，但 Canvas 画笔实现推到后续迭代
- **生成状态恢复（后台轮询）**：SSE 断线重连机制较复杂，暂不实现
- **选段生成分镜**：需要 Web 端编辑器选中文字交互，移动端不适用
- **批量下载**：移动端下载能力受平台限制，暂不实现
- **分镜拖拽排序**：需 drag 库，暂不实现
