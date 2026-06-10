# 导出导入功能设计文档

**日期**: 2026-05-17
**项目**: Manwen-Studio (LoreVista)
**状态**: 已批准

---

## 1. 概述

为小说创作工作台增加导出导入功能，支持用户：
- **导出**：将小说作品（大纲、角色设定、章节正文、漫画图片）导出为 ZIP 压缩包，内含 JSON 备份和 Markdown 正文，便于发布到小说创作平台
- **导入**：用户上传已有的小说文件（txt/md/docx），系统智能识别章节结构，创建小说并借助 AI 分析生成框架（标签、角色、大纲）

---

## 2. 导出功能

### 2.1 技术方案

纯前端实现，不依赖后端新增接口。使用 `jszip` 库打包，`file-saver` 触发浏览器下载。

### 2.2 依赖

- `jszip` — 前端 ZIP 打包
- `file-saver` — 浏览器文件下载

### 2.3 数据来源

通过现有 API 获取：
- `GET /api/stories/{id}` — 获取小说信息（含 tags/outline/characters）
- `GET /api/stories/{id}/chapters` — 获取章节列表
- `GET /api/chapters/{id}` — 获取单章详情（含 messages/images）
- `mangaImageUrl()` — 获取漫画图片 URL（用于下载图片）

### 2.4 ZIP 包结构

```
小说名称_export_2026-05-17.zip
├── 小说信息.json                    ← 完整 JSON 备份（可重新导入）
├── 小说正文.md                       ← 完整小说正文 Markdown
├── 01_故事大纲.md                    ← 三幕式大纲
├── 02_角色设定.md                    ← 角色详情
├── 03_章节内容/                     ← 每章独立 Markdown 文件
│   ├── 第01话_章节标题.md
│   ├── 第02话_章节标题.md
│   └── ...
└── images/                          ← 漫画图片（可选包含）
    ├── chapter_1/
    │   ├── panel_01.png
    │   └── ...
    └── ...
```

### 2.5 小说正文.md 格式

```markdown
# 小说标题

> 小说简介

---

## 第1话 标题

正文内容...

### 关键事件

- 事件1
- 事件2

---

## 第2话 标题

正文内容...
```

### 2.6 故事大纲.md 格式

```markdown
# 故事大纲 - 小说标题

## 第一幕：开端（25%）

> 第一幕总结

### 第1话 标题
- 关键事件1
- 关键事件2

### 第2话 标题
...

## 第二幕：中段（50%）
...
```

### 2.7 角色设定.md 格式

```markdown
# 角色设定 - 小说标题

## 主角：角色名

**角色定位**：主角

**大五人格**：
- 开放性：75
- 尽责性：60
- 外向性：45
- 宜人性：80
- 情绪性：35

**动机**：...
**恐惧**：...

**关系**：
- 角色B · 师徒
- 角色C · 对手
```

### 2.8 小说信息.json 格式

```json
{
  "version": 1,
  "exported_at": "2026-05-17T10:00:00Z",
  "story": {
    "title": "小说标题",
    "description": "简介",
    "tags": { "type": "奇幻", "theme": "冒险" },
    "characters": [
      {
        "name": "角色名",
        "role": "主角",
        "big_five": { "O": 75, "C": 60 },
        "arc": { "motivation": "...", "fear": "..." },
        "relationships": [
          { "character": "角色B", "relationship": "师徒" }
        ]
      }
    ],
    "outline": {
      "three_acts": [
        {
          "act": 1,
          "title": "第一幕",
          "summary": "...",
          "chapters": [
            { "chapter_number": 1, "title": "第1话", "summary": "...", "key_events": ["..."] }
          ]
        }
      ],
      "themes": ["..."]
    }
  },
  "chapters": [
    {
      "chapter_number": 1,
      "title": "第1话",
      "act": "1",
      "status": "completed",
      "novel_content": "正文内容...",
      "key_events": ["..."],
      "word_count": 4521,
      "quality_score": { "overall": 85 }
    }
  ],
  "messages": [
    { "chapter_number": 1, "role": "user", "content": "..." }
  ]
}
```

---

## 3. 导入功能

### 3.1 技术方案

前后端协作：
- **后端**：负责文件解析（含 python-docx 解析 docx）、章节检测、DeepSeek AI 分析、数据持久化
- **前端**：负责文件选择、上传、预览展示、交互确认

### 3.2 新增后端依赖

- `python-docx` — 解析 `.docx` 文件

### 3.3 新增后端端点

#### 3.3.1 `POST /api/import/parse`

上传并解析文件，检测章节结构。

**请求**: `multipart/form-data`，字段 `file`

**响应**:
```json
{
  "detected_title": "检测到的书名",
  "chapters": [
    {
      "chapter_number": 1,
      "title": "第1话",
      "content": "正文内容...",
      "detection_method": "regex"  // "regex" | "ai"
    }
  ],
  "total_word_count": 50000
}
```

**处理逻辑**:
1. 根据文件扩展名选择解析器（txt/md/docx）
2. 提取纯文本内容
3. 章节检测（两级策略）:
   - **一级 - 正则匹配**: 匹配 `第[一二三四五六七八九十百零0-9]+[章话节回]`、`## `、`# ` 等模式
   - **二级 - AI 分析**: 无匹配或匹配过少时，调用 DeepSeek API 分析内容划分章节
4. 返回检测结果

#### 3.3.2 `POST /api/import/create`

确认导入，创建小说和章节。

**请求**:
```json
{
  "title": "小说标题",
  "description": "简介（可选）",
  "chapters": [
    {
      "chapter_number": 1,
      "title": "第1话",
      "content": "正文内容...",
      "act": "1",
      "key_events": ["事件1"]
    }
  ],
  "analyze_framework": true
}
```

**响应**: `Story` 对象

**处理逻辑**:
1. 创建 Story（`POST /api/stories` 的等价逻辑）
2. 创建所有 Chapters，填充 novel_content
3. 若 `analyze_framework=true`，自动触发框架分析

#### 3.3.3 `POST /api/stories/{story_id}/framework/analyze`

从已有章节正文分析生成框架（tags/characters/outline）。

**请求**: 无 body

**响应**:
```json
{
  "tags": { "type": "奇幻", "theme": "冒险" },
  "characters": [...],
  "outline": { "three_acts": [...] }
}
```

**处理逻辑**:
1. 读取该 Story 下所有 Chapters 的 novel_content
2. 拼接前 N 章内容（考虑 token 限制）
3. 调用 DeepSeek API 分析内容，提取：
   - 标签分类（type/theme/style/audience）
   - 角色列表（name/role/big_five/arc/relationships）
   - 大纲结构（three_acts）
4. 更新 Story 的 tags/characters/outline 字段

### 3.4 章节检测算法

```
function detectChapters(text):
    // 策略1：正则匹配常见章节标题模式
    patterns = [
        /第[一二三四五六七八九十百零0-9]+[章话节回]/,
        /^#{1,3}\s+.+/m,           // Markdown 标题
        /^[0-9]+\.\s+.+/m,         // 数字序号
        /^第[零一二三四五六七八九十百千]+[章话节回]/
    ]
    
    matches = find_all(text, patterns)
    
    if matches.length >= 2:
        // 有明确的章节结构 → 按匹配位置切割
        return split_by_positions(text, matches)
    
    // 策略2：AI 分析
    return ai_analyze_and_split(text)
```

### 3.5 前端新增/修改组件

#### 新建: `ImportDialog.tsx`

状态驱动的对话框组件：

```
[选择文件] → [上传中...] → [预览章节] → [导入完成]
```

- 文件拖拽/选择区域
- 上传进度指示
- 章节列表预览（可编辑标题）
- 确认导入按钮
- 导入成功 → 跳转至工作台

#### 修改: `HomePage.tsx`

- 标题栏添加「导入小说」按钮
- 每个故事卡片菜单添加「导出」选项

#### 修改: `WorkspaceLayout.tsx`

- 工具栏添加「导出」按钮

### 3.6 导入流程完整交互

```
作品列表页
    │ 点击「导入小说」
    ▼
┌─────────────────────────────────────┐
│  选择文件 (支持 .txt .md .docx)     │
│  ┌─────────────────────────────┐   │
│  │  拖拽文件到此处，或点击选择   │   │
│  └─────────────────────────────┘   │
│  文件大小限制: 10MB                │
│  [取消]                    [下一步] │
└─────────────────────────────────────┘
    │ 选择文件 → 上传到 /api/import/parse
    ▼
┌─────────────────────────────────────┐
│  章节预览 (检测到 N 章)             │
│                                     │
│  ┌─ 第1话 标题xxx ──────────────┐  │
│  │  内容预览前 100 字...         │  │
│  └───────────────────────────────┘  │
│  ┌─ 第2话 标题xxx ──────────────┐  │
│  │  内容预览前 100 字...         │  │
│  └───────────────────────────────┘  │
│  ...                                │
│                                     │
│  [返回]          ☑ AI 生成小说框架  │
│                    [确认导入]       │
└─────────────────────────────────────┘
    │ 确认 → 调用 /api/import/create
    ▼
┌─────────────────────────────────────┐
│  导入成功！                         │
│  《小说标题》 已创建                │
│  N 章已导入                        │
│  (框架已生成)                       │
│                                     │
│           [进入创作工作台]          │
└─────────────────────────────────────┘
```

---

## 4. 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/main.py` | 新增 3 个端点 | `POST /api/import/parse`, `POST /api/import/create`, `POST /api/stories/{id}/framework/analyze` |
| `backend/schemas.py` | 新增 | 导入相关 Pydantic schema（ParseResult, ImportRequest, AnalyzeResult） |
| `backend/requirements.txt` | 新增依赖 | 添加 `python-docx` |
| `frontend/package.json` | 新增依赖 | 添加 `jszip`, `file-saver`（或 `@types/jszip`, `@types/file-saver`） |
| `frontend/src/api.ts` | 新增 3 个函数 | `parseImportFile()`, `createImportStory()`, `analyzeFramework()` |
| `frontend/src/components/ImportDialog.tsx` | **新建** | 导入对话框组件 |
| `frontend/src/components/HomePage.tsx` | 修改 | 添加「导入小说」「导出」按钮 |
| `frontend/src/components/WorkspaceLayout.tsx` | 修改 | 添加「导出」按钮 |

---

## 5. 约束与限制

- **文件大小上限**: 10MB（与现有上传一致）
- **支持格式**: `.txt`（UTF-8）、`.md`（UTF-8）、`.docx`
- **章节数上限**: 单次导入最多 500 章
- **AI token 限制**: 分析框架时，若小说过长，仅取前 5 章内容进行分析（后续章节的结构可以从大纲体现）
- **图片导入**: 导入阶段不处理图片，仅导入文本内容

---

## 6. 未涉及范围（后续迭代）

- EPUB 格式导入/导出
- 导出为 PDF
- 批量导出多部小说
- 导入时连带图片资源
