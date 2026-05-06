# InkAI 集成到 LoreVista — 设计文档

> 日期：2026-05-06
> 状态：待审阅

## 1. 概述

### 1.1 当前问题

LoreVista 的小说生成流程是「自由聊天 → 生成小说」模式，缺乏整体框架约束：
- 无标签体系、无角色模型、无故事大纲
- 只有一个笼统的 `NOVEL_SYSTEM_PROMPT` 指导生成
- 用户无法看到或控制小说的整体结构
- 没有质量评估机制

### 1.2 目标

将 InkAI 的 7-agent 结构化小说生成框架（标签 → 角色 → 大纲 → 章节 → 质量评估）集成到 LoreVista 的 Web 界面中，实现：
1. **三栏式工作台**：左侧框架 | 中间编辑 | 右侧漫画
2. **AI 辅助框架生成**：一键生成 + 逐模块单独优化
3. **框架约束的章节生成**：每章严格跟随大纲、角色、关键事件
4. **框架联动漫画**：左侧选中框架内容 → 右侧分镜/漫画

### 1.3 技术原则

- 不引入 InkAI Python 代码依赖
- 提取 InkAI 的 prompt 模板和知识库为 TypeScript 配置
- 沿用 LoreVista 现有技术栈（React + FastAPI + DeepSeek + PostgreSQL）

---

## 2. 整体布局

```
┌────────────────────────────────────────────────────────────┐
│  Header Bar (故事标题 · 导出 · 设置)                       │
├───────────────┬───────────────────────┬────────────────────┤
│  LEFT  280px  │  CENTER  flex:1      │  RIGHT  380px      │
│  小说框架      │  小说编辑区            │  漫画工作台         │
├───────────────┼───────────────────────┼────────────────────┤
│ ▼ 🏷 标签     │ [章节Tab栏]           │  分镜列表           │
│ ▼ 👤 角色     │ 章节内容 + 编辑       │  Scene 1 [重新生成] │
│ ▼ 📖 大纲     │                      │  Scene 2 [重新生成] │
│ ▼ 📑 章节     │ [AI生成][改写][分镜] │  [选中文字→分镜]   │
│ [AI生成框架]  │                      │  [生成全部漫画]     │
└───────────────┴───────────────────────┴────────────────────┘
```

核心交互：
- **左侧选中** → 中间显示对应内容
- **中间选中文字** → 右侧基于选中文字生成分镜
- **左侧框架** 是中间编辑的约束源
- **右侧漫画** 是中间文字的视觉输出

---

## 3. 左侧面板：小说框架

### 3.1 结构

```
┌─────────────────────────┐
│  [故事描述输入框]        │
│  [✨ AI 生成框架]        │  ← 一键生成全部
├─────────────────────────┤
│  ▼ 🏷 标签               │
│    都市 · 爽文 · 系统    │
│    [🔄 重新生成]         │
├─────────────────────────┤
│  ▼ 👤 角色 (3)           │
│    ┌─ 主角: 林风 ────┐  │
│    │ O65 C72 E30...  │  │
│    │ 动机: 复仇      │  │
│    └─────────────────┘  │
│    [+ 添加角色]         │
│    [🔄 AI 生成角色]     │
├─────────────────────────┤
│  ▼ 📖 大纲               │
│    Act 1 (25%) ─ 建立    │
│    ├ Ch1: 意外获得系统   │
│    ├ Ch2: 初次尝试       │
│    └ Ch3: 遭遇危机       │
│    Act 2 (50%) ─ 对抗    │
│    Act 3 (25%) ─ 高潮    │
│    [🔄 优化大纲]         │
├─────────────────────────┤
│  ▼ 📑 章节 (15)          │
│    第1话 · 意外获得系统  │
│    第2话 · 初次尝试      │
│    [+ AI 续写章节]       │
│    [📊 质量评分]          │
└─────────────────────────┘
```

### 3.2 交互规则

| 操作 | 行为 |
|------|------|
| 输入故事描述 +「AI 生成框架」| 调用后端 `/framework/generate`，一次性生成标签+角色+大纲+章节规划 |
| 每个模块底部的「🔄」按钮 | 调用对应独立端点，仅重新生成该模块 |
| 点击角色卡片 | 中间显示角色详情，可 AI 对话该角色 |
| 点击大纲节点/章节 | 中间切换到对应章节Tab，加载/生成该章节内容 |
| 大纲节点选中 | 状态传递给右侧漫画工作台，供分镜参考 |

### 3.3 框架生成方式（两者结合）

- **一键生成**：顶部输入故事描述，AI 全自动生成框架
- **逐模块优化**：每个模块可单独触发 AI 重新生成/修改
- **手动编辑**：所有生成内容可手动修改

---

## 4. 中间面板：小说编辑区

### 4.1 结构

```
┌─────────────────────────────────────────────┐
│ [第1话] [第2话] [第3话] ... [第15话]        │  ← 章节Tab栏
│                               [+ 新建章节] │
├─────────────────────────────────────────────┤
│ ┌─ 第2话 · 初次尝试 ───────── [💾保存] ──┐ │
│ │                                         │ │
│ │  📋 大纲约束：Act1-建立阶段              │ │  ← 框架提示条
│ │  🎯 关键事件：获得系统后第一次使用能力    │ │
│ │  👤 出场角色：林风                       │ │
│ │  ───────────────────────────────        │ │
│ │                                         │ │
│ │  [选中文字] 林风站在镜子前...            │ │
│ │                                         │ │
│ │  他缓缓抬起右手，指尖泛起微弱的蓝光...   │ │  ← 选中文字同步到右侧
│ │                                         │ │
│ │  "这就是系统的力量吗？"他喃喃自语。     │ │
│ │                                         │ │
│ │  窗外的城市灯火通明...                   │ │
│ └─────────────────────────────────────────┘ │
├─────────────────────────────────────────────┤
│ [🤖 AI 生成此章节] [📝 AI 改写选中]         │
│ [🎨 选中文字→分镜]  [📊 质量评估]          │
└─────────────────────────────────────────────┘
```

### 4.2 操作

| 操作 | 触发 | 效果 |
|------|------|------|
| 选章节 | 左侧点击大纲节点/章节 | 切换到对应Tab，加载已有内容或显示空模板 |
| AI 生成此章节 | 底部按钮 | 根据大纲约束+角色信息，调用 DeepSeek 生成 |
| AI 改写选中 | 选中文字+按钮 | 局部改写选中段落，保持上下文连贯 |
| 选中文字→分镜 | 选中文字+按钮 | 将选中文本发送到右侧，触发分镜生成 |
| 质量评估 | 底部按钮 | 5维度打分 + 改进建议 |
| 框架提示条 | 始终显示 | 顶部展示大纲位置、角色、关键事件约束 |

---

## 5. 右侧面板：漫画工作台

保留现有 MangaPanel 功能，新增联动接口：

### 5.1 联动逻辑

```
中间编辑器选中文字
    ↓ POST /api/chapter/{id}/scenes-from-selection
    ↓ 传递: { selected_text, chapter_context, character_profiles, page_count? }
    ↓ DeepSeek 生成分镜描述
    ↓ 右侧面板刷新分镜列表
    ↓ 逐张生成漫画图片
```

### 5.2 结构

```
┌─────────────────────────────┐
│  漫画工作台                  │
├─────────────────────────────┤
│  📋 分镜列表                 │
│  ┌─ Scene 1 ─────────────┐  │
│  │ 描述：林风站在镜子前.. │  │
│  │ [🖼 生成] [🔄 重生成]   │  │
│  │ [图片]                 │  │
│  └────────────────────────┘  │
│  ┌─ Scene 2 ─────────────┐  │
│  │ ...                   │  │
│  └────────────────────────┘  │
│                             │
│  [📝 编辑全部场景]          │
│  [🎨 从选中文本生成分镜]     │  ← 新增联动
│  [🖼 生成全部漫画]          │
└─────────────────────────────┘
```

### 5.3 与现有 MangaPanel 的关系

- 复用现有 `MangaPanel.tsx` 核心逻辑
- 新增 props: `selectedText?: string`、`chapterContext?: object`
- 新增入口: 中间编辑区「选中文字→分镜」按钮
- 新增 API: `POST /api/chapter/{id}/scenes-from-selection`

---

## 6. 数据模型变更

### 6.1 Story 模型扩展

```python
# backend/models.py

class Story(Base):
    # ... 现有字段 ...
    tags = Column(JSON, nullable=True)          # {"type":"都市","theme":"爽文","style":"热血","audience":"男频"}
    outline = Column(JSON, nullable=True)       # {"three_acts":[...],"themes":[...],"foreshadowing":[...]}
    characters = Column(JSON, nullable=True)    # [{"name":"林风","role":"主角","big_five":{...},"arc":{...},"relationships":[...]}]
```

### 6.2 Chapter 模型扩展

```python
class Chapter(Base):
    # ... 现有字段 ...
    act = Column(String, nullable=True)         # "act1" | "act2" | "act3"
    key_events = Column(JSON, nullable=True)    # [{"event":"意外获得系统","status":"completed"}]
    quality_score = Column(JSON, nullable=True) # {"content":85,"writing":78,..."overall":82}
    status = Column(String, default="pending")  # "pending"|"draft"|"completed"|"reviewed"
    word_count = Column(Integer, nullable=True) # 字数统计
```

---

## 7. API 端点

### 7.1 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/story/{id}/framework/generate` | AI 一键生成完整框架（标签+角色+大纲+章节） |
| POST | `/api/story/{id}/framework/tags` | 单独重新生成标签 |
| POST | `/api/story/{id}/framework/characters` | 单独生成/重新生成角色 |
| POST | `/api/story/{id}/framework/outline` | 单独优化大纲 |
| POST | `/api/story/{id}/framework/expand-chapter` | 大纲节点展开为章节内容 |
| POST | `/api/chapter/{id}/rewrite-selection` | AI 改写选中文本 |
| POST | `/api/chapter/{id}/quality-assess` | 质量评估 |
| POST | `/api/chapter/{id}/scenes-from-selection` | 从选中文字生成分镜（漫画联动） |

### 7.2 改造端点

| 方法 | 路径 | 变更 |
|------|------|------|
| POST | `/api/chapter/{id}/generate-novel` | prompt 注入框架约束（大纲、角色、关键事件） |
| POST | `/api/chapter/{id}/chat` | system prompt 包含当前章节的框架上下文 |

---

## 8. InkAI 知识注入方式

### 8.1 不引入 Python 代码

InkAI 使用智谱 AI（ZhipuAI），LoreVista 使用 DeepSeek。两者 LLM 提供商不同，不直接复用 InkAI 的 `base_agent.py`。

知识提取方式：开发者手动阅读 InkAI 各 agent 源文件中的 `_build_*_prompt()` 方法和内置知识库（标签字典、兼容矩阵、Big Five Traits 定义、写作技巧字典等），将结构化知识提取为 TypeScript 配置文件。这是一次性手动翻译工作，不涉及自动化工具。

### 8.2 Prompt-Level 集成

将 InkAI 7个 agent 的 **prompt 模板 + 知识库** 提取为独立文件：

```
frontend/src/prompts/
├── inkai-tags.ts            ← 70+标签体系、兼容矩阵、流行组合
├── inkai-characters.ts      ← Big Five 模型、职业特质库、角色原型
├── inkai-storyline.ts       ← 三幕结构、冲突类型、伏笔管理模板
├── inkai-chapter.ts         ← 写作技巧库、风格模板、字数控制
└── inkai-quality.ts         ← 5维度评分标准、质量等级定义
```

### 8.3 后端调用方式

前端将选定的 prompt 模板参数发送给后端，后端拼接到 DeepSeek 的 system prompt 中：

```python
# backend/services/deepseek.py

FRAMEWORK_SYSTEM_PROMPT = """
你是一个专业的小说框架设计师。请根据用户的故事描述，生成完整的小说框架。

## 标签体系
{inkai_tags_knowledge}

## 角色模型
{inkai_character_knowledge}

## 故事结构
{inkai_storyline_knowledge}

请按照以下 JSON 格式输出...
"""
```

---

## 9. 前端组件树

### 9.1 现有组件关系

```
App.tsx
├── HomePage.tsx          ← 故事列表/创建
└── EditorLayout          ← 编辑器（需新增）
    ├── ChatPanel.tsx     ← 对话模式
    └── MangaPanel.tsx    ← 漫画工作台
```

### 9.2 目标组件树

```
App.tsx
├── HomePage.tsx              ← 故事列表/创建（保留）
└── WorkspaceLayout           ← 新增：三栏工作台
    ├── FrameworkPanel.tsx    ← 新增：左侧框架
    │   ├── TagSection
    │   ├── CharacterSection
    │   ├── OutlineSection
    │   └── ChapterListSection
    ├── EditorPanel.tsx       ← 新增：中间编辑区
    │   ├── ChapterTabBar
    │   ├── FrameworkContextBar
    │   ├── TextEditor
    │   └── EditorToolbar
    └── MangaPanel.tsx        ← 改造：右侧漫画（复用+联动）
        ├── SceneList
        └── ImageGenerator
```

---

## 10. 实施路线

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | 数据模型扩展（Story + Chapter 新增字段） | P0 |
| **Phase 2** | Prompt 知识库提取（InkAI → TypeScript） | P0 |
| **Phase 3** | 后端 API（框架生成、约束注入、质量评估） | P0 |
| **Phase 4** | WorkspaceLayout + FrameworkPanel（左侧） | P0 |
| **Phase 5** | EditorPanel（中间编辑区） | P0 |
| **Phase 6** | MangaPanel 联动改造 | P1 |
| **Phase 7** | 一键生成流程打通 + 端到端测试 | P1 |

---

## 11. 风险与注意事项

- DeepSeek 与智谱 AI 对 prompt 的响应风格差异，需调优 InkAI prompt 模板适配 DeepSeek
- 框架生成的多轮 LLM 调用耗时长，需做好 loading 状态和进度反馈
- 三栏布局在移动端不可用，需保留现有移动端单栏模式作为 fallback
- 大数据量章节的内容编辑性能问题，考虑虚拟滚动
