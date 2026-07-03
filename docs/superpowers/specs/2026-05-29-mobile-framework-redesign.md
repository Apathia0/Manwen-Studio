# 移动端框架页重构设计

## 背景

移动端 `framework.vue` 当前功能严重落后于 web 前端。主要问题：

1. 三区（标签/角色/大纲）均为只读，无法编辑
2. 大纲中无内容章节点击无响应
3. 缺少 AI 框架对话（web 的 FrameworkPanel 核心功能）
4. 缺少章节列表视图及其操作
5. 缺少历史版本快照和回滚

## 目标

- 功能对齐 web 端 FrameworkPanel
- 交互适配移动端（iOS 风格）
- 无内容章节可点击操作（生成正文或打开编辑器）

## 设计方案

### 页面结构

保留单页滚动结构，顶部导航栏 + 可折叠分区卡片：

```
Navbar: 「← 故事框架」 + [全部展开/收起]
│
├── 故事描述（新增，可编辑）
├── 框架 （新增，约 250px 高对话区）
├── 标签设定（增强，可编辑）
├── 角色设定（增强，可展开详情）
├── 故事大纲（核心改造）
└── 章节列表（新增）
```

### 各区域设计

#### 1. 故事描述
- 文本展示 + 编辑按钮
- 点击进入编辑模式

#### 2. 框架 
- 对话气泡列表（用户/AI 角色）
- 底部输入框 + 发送按钮
- 「一键续写」按钮 → `continueFramework()`
- 「历史版本」按钮 → 展开快照列表 → 回滚
- 首次使用：输入故事描述 → `generateFramework()`
- 已有框架：输入修改建议 → `adjustFramework()`

#### 3. 标签设定
- 标签展示（保留现有样式）
- 右上角「编辑」按钮 → 内联编辑模式
- 支持修改已生成标签

#### 4. 角色设定
- 角色卡片列表（保留现有）
- 展开详情展示大五人格/弧光/关系（web 角色卡片深度）

#### 5. 故事大纲（核心改造）
- 每幕为一个可折叠卡片
- 幕标题：名称 + 百分比（该幕章节数占比）
- 幕摘要（可展开）
- 每个章节节点：
  - 章节编号 + 标题
  - 摘要（一行，可展开）
  - 目标/冲突/钩子/回报（可选，可展开）
  - **操作按钮**：
    - 无内容（`novel_content` 为空）→「生成正文」按钮，调用 `expandChapter()`
    - 有内容 →「打开」按钮，跳转到 `chapter-view`

#### 6. 章节列表
- 扁平列表，每项显示：编号、标题、状态（待生成/草稿/已发布）
- 顶部「AI 生成章节」按钮（调 `regenerateOutline()`）
- 每个章节可展开操作菜单：
  - 打开正文
  - 生成正文（无内容时）
  - 质量评估（有章节 ID 时）
  - 编辑规划
  - 在后面插入

### 导航跳转

从框架页点击章节时的跳转路径：

```
// 有内容的章节
uni.navigateTo(`/pages/workspace/chapter-view?storyId=${id}&chapterNumber=${n}`)

// 无内容的章节 → 先生成再跳转
await expandChapter(story.id, {...})
uni.navigateTo(`/pages/workspace/chapter-view?storyId=${id}&chapterNumber=${n}`)

// 框架 （一键续写）
await continueFramework(story.id)
// 刷新页面数据

// 历史版本回滚
await restoreFrameworkSnapshot(story.id, snapshotId)
// 刷新页面数据
```

### iOS 风格视觉

- 导航栏：大标题模式（iOS large title），毛玻璃背景
- 卡片：圆角 20rpx，浅灰底 `#f8f9fc`，无边框
- 间距：宽松 `24rpx` 呼吸式 padding
- 动画：展开/收起带弹簧缓动
- 操作按钮：SF Symbols 风格图标 + 文字

### 数据流

```
framework.vue (onLoad)
  ├── storiesApi.getStory(storyId) → tags, characters, outline
  │
  ├── AI对话 → storiesApi.generateFramework / adjustFramework / continueFramework
  │           → 完成后重新加载故事
  │
  ├── 快照 → storiesApi.listFrameworkSnapshots / restoreFrameworkSnapshot
  │
  ├── 生成正文 → storiesApi.expandChapter → 跳转 chapter-view
  │
  └── 质量评估 → storiesApi.assessQuality
```

### 涉及 API

（全部已有，不需要新增）

- `GET /api/stories/{id}` — 获取故事（含 tags/characters/outline）
- `POST /api/stories/{id}/framework/generate` — 首次生成框架
- `POST /api/stories/{id}/framework/adjust` — AI 调整框架
- `POST /api/stories/{id}/framework/continue` — 续写框架
- `GET /api/stories/{id}/framework-snapshots` — 快照列表
- `POST /api/stories/{id}/framework-snapshots/{id}/restore` — 回滚
- `POST /api/stories/{id}/expand-chapter` — 生成正文
- `POST /api/stories/{id}/outline/regenerate` — 重新生成大纲/章节
- `PUT /api/stories/{id}` — 更新故事（保存框架手动编辑）
- `POST /api/chapters/{id}/assess-quality` — 质量评估

### 文件变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/pages/workspace/framework.vue` | 重写 | 主要改造 |
| `src/components/outline-tree/outline-tree.vue` | 重写 | 增强为可交互 |
| `src/components/framework-section/framework-section.vue` | 保留 | 可折叠组件复用 |
| `src/components/character-card/character-card.vue` | 增强 | 展开更多详情 |
| `src/api/types.ts` | 补充 | 如有必要增加新类型 |
| `src/api/index.ts` | 补充 | 如有必要增加新 API 封装 |
