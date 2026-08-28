# 漫剧创作画布化改造开发文档

> 分支：`codex/video-canvas-three-node`（在 codex 分支开发，测试通过后合入 `pro`）
> 状态：**v2 待审查** — v1 已获口头确认（Q1-Q5 按默认方案），v2 新增"小说章节导入剧本 + 编辑后拆分"能力（§3.7、§4 阶段 3.5）
> 日期：2026-08-28

---

## 0. 背景与目标

### 0.1 用户反馈驱动的三个核心决策

| # | 决策 | 依据 |
|---|------|------|
| D1 | **移除分镜列表功能**（UI 层下线，数据层保留） | 用户实测效果差。根因已定位：`video_chapter_prompts.py` 中 15 秒硬约束（"固定时长"、"时间总和必须严格等于"、"信息不足必须补足"）迫使 AI 注水填充空镜 |
| D2 | **视频漫剧创作独立成菜单**，不再与小说/漫画共用工作台 | 视频工作流与小说章节结构强耦合（`chapter_video_shot` 挂在章节下），但漫剧创作实际是"剧本→分镜→视频"的独立创作流 |
| D3 | **全面画布模式**：新建画布项目 → 空白画布 → 画布 Agent 对话生成剧本 → 剧本节点拆分 → 动态时长视频节点 | 分镜列表效果差的部分原因也是"列表形态"本身不适合表达镜头序列的编排关系 |

### 0.2 动态时长的技术可行性（已验证）

- 底层 `create_video_job()` 支持 `duration_seconds` 任意值（默认 5s），仅 Seedance 1.x 有 ≤12s 上限校验（`video_api.py:validate_legacy_model_duration`）。**上游 API 不要求 15 秒**，15 秒是管线层自缚。
- `deepseek.py:4675/4793` 拆分结果已读取 `shot_data.get("duration_seconds", 15)`，即拆分 JSON 协议本身已有 duration 字段，只是 prompt 强制 15 秒。
- `video_canvas_runtime.py:432/525` 画布运行时已支持每节点独立 `duration_seconds`。

### 0.3 非目标（明确不做）

- 不改 `chapter_video_shot` 等视频数据模型（旧项目兼容 + 合片链路复用）
- 不动小说、漫画工作台
- 不做画布多人协作
- 不在本轮做手机端适配（画布仅桌面端）

---

## 1. 现状盘点（codex 分支已有能力）

### 1.1 后端（可直接复用）

| 模块 | 位置 | 状态 |
|------|------|------|
| 画布数据模型 | `models.py`: VideoCanvas / VideoCanvasVersion / VideoCanvasLayout / VideoCanvasPlan / VideoCanvasRun / VideoCanvasRunNode / VideoCanvasSyncRecord | ✅ 完整 |
| 图协议校验 | `routers/video_canvas.py`: NODE_CATALOG（text/image/video 三类公开节点 + legacy 兼容）+ `_validate_graph`（类型/环/节点ID安全） | ✅ 完整 |
| 画布运行时 | `services/video_canvas_runtime.py`（614 行）：节点执行、图片/视频生成、计费埋点、每节点 duration_seconds | ✅ 完整 |
| 画布 Agent 工具 | `agent_service.py`: `get_canvas_graph` / `resolve_canvas_source` / `create_canvas_plan` / `update_canvas_plan` / `apply_canvas_ops` + 4 个 director 工作流（canvas_screenplay_director 已存在） | ✅ 骨架已有 |
| Agent 画布写入 | pending-changes 的 `video_canvas_graph` 类型 + 版本化回滚 | ✅ 完整 |
| 剧本拆分 | `deepseek.py: split_scenes` + `_parse_lite_chunk/_parse_full_chunk` + `_repair_truncated_json` | ✅ 可复用，需改 prompt |
| 视频提交 | `video_api.create_video_job`（input_reference 管道符格式）+ 档位校验 | ✅ 可复用 |

### 1.2 前端（可直接复用）

| 模块 | 位置 | 状态 |
|------|------|------|
| 画布交互层 | `components/video-canvas/`（11 个文件，useCanvasInteractions 756 行）：锚点缩放、框选、连线吸附、贝塞尔连线、小地图、右键菜单、创建菜单、撤销重做 | ✅ 完整（infinite-canvas MIT 移植） |
| 画布面板 | `VideoCanvasPanel.tsx`（956 行）：节点 CRUD、图保存/校验/运行、与列表视图互切 | ✅ 完整 |
| 入口 | `VideoStoryboardLayout.tsx` 列表/画布双 Tab 切换 | ⚠️ 将改造 |

### 1.3 关键差距（本开发要补的）

| # | 差距 | 说明 |
|---|------|------|
| G1 | 漫剧创作无独立菜单 | 目前 `workspaceMode === 'video'` 挂在小说工作台 |
| G2 | 画布无"剧本→视频节点组"的自动展开 | screenplay 拆分后需自动生成一组带各自时长的 video 节点 |
| G3 | 拆分 prompt 固定 15 秒 | 需改为动态时长 + 内容密度理由 |
| G4 | 提交前无时长档位归一化 | AI 说 7 秒需归一到上游支持的档位 |
| G5 | 画布 Agent 不能"对话生成剧本" | canvas_screenplay_director 存在但工具链面向既有章节来源，缺"从零对话创作剧本"路径 |
| G6 | 分镜列表入口未下线 | 需 feature flag 控制 |
| G7 | 剧本无"用户可自由编辑"环节 | 现有 plan 流是 AI 生成→用户确认，缺"用户改完剧本再拆分"的回路（v2 新增需求核心） |
| G8 | 章节来源被锁死在画布所属作品 | `_resolve_canvas_source_snapshot` 强制 `chapter.story_id == canvas.story_id`，无法选**其他**小说作品的章节正文作为剧本来源（v2 新增需求核心） |

---

## 2. 目标架构

### 2.1 用户旅程（改造后）

漫剧项目支持**三种剧本来源**，殊途同归汇入"剧本编辑 → 拆分 → 视频节点组"主流程：

```
顶部导航「漫剧创作」（独立菜单，不再藏于小说工作台）
   │
   ▼
漫剧项目列表（story_type='video' 的项目，见 §3.1）
   │ 新建项目 ── 选择剧本来源（三选一，可跳过后补）
   │
   ├─【来源 A：对话创作】──► 空白画布 + Agent 面板
   │      用户与画布 Agent 对话 → Agent 生成剧本草稿
   │      → 确认后写入画布「剧本」节点
   │
   ├─【来源 B：导入小说章节】──► 章节选择器（跨作品）
   │      选择用户名下任意小说作品的章节正文（可多选、可排序）
   │      → 生成画布「剧本」节点（携带章节来源快照与 source_hash）
   │
   └─【来源 C：手动粘贴】──► 空白剧本节点，用户直接输入
   │
   ▼
═══ 剧本编辑回路（v2 核心）═══
   剧本节点可随时自由编辑（节点内编辑器 / Agent 对话修改），
   编辑产生新版本；拆分永远以当前剧本内容为准
   │
   ▼ 用户点击剧本节点「拆分」（或对话指令）
后端按当前剧本内容动态拆分（复用现有剧本拆分模块）
   → 每个视频单元带建议时长（3-15s）+ 密度理由
   │  拆分结果以 pending-change 呈现，用户确认
   ▼
画布自动展开一组「视频」节点（网格布局，横向时间序），
每个节点写入 duration_seconds + storyboard prompt
   │  用户逐节点或批量「生成」
   ▼
各视频节点运行 → 故事版图（可选）→ 视频生成
   │
   ▼
「合片」节点（concat）按画布连线顺序拼接 → 输出节点导出
```

**关键闭环**：拆分不满意 → 回到剧本编辑（改剧本或让 Agent 改）→ 重新拆分 → 旧的视频节点组被新组替换（版本化，可回退）。剧本内容和拆分结果通过 `source_hash` 绑定，剧本变更后旧拆分自动标记过期。

### 2.2 数据流（复用为主）

```
画布 Agent（对话创作剧本）
  → agent_service（canvas_screenplay_director 扩展）
  → pending_changes[video_canvas_graph] → 用户确认
  → VideoCanvasVersion 新版本（剧本文本节点）

剧本节点「拆分」
  → POST /api/video-canvas/canvases/{id}/screenplay-split
  → deepseek.split_scenes（新动态时长 prompt）
  → 返回视频单元列表[{title, summary, prompt, duration_seconds, reason}]
  → 前端自动布局生成 video 节点组 → PUT graph（版本化）

视频节点运行
  → video_canvas_runtime（已有）
  → create_video_job(duration_seconds=节点值)
  → OSS 上传 → video_outputs 落盘

合片
  → concat 节点（已有）→ video_compiler
  → ⚠️ 需验证：段间音画对齐（见 §6 风险）
```

---

## 3. 关键设计决策（需审查确认）

### 3.1 「漫剧项目」的数据定位

**方案 A（推荐）：漫剧项目 = 独立 Story（`story_type='video'`）**
- 复用 Story 的所有权/配额/Agent 会话体系，只加一个类型字段区分
- 漫剧项目不显示小说章节 Tab；工作台直接进画布
- 迁移成本最低

**方案 B：全新 MangaProject 表**
- 数据干净但配额/认证/会话全部要接第二遍，成本高

> 采用 A。`stories` 表加 `story_type` 列（`novel` 默认 / `video`），增量迁移幂等。

### 3.2 分镜列表的下线方式

- 前端：`VideoStoryboardLayout` 的列表 Tab 用 feature flag `VITE_ENABLE_SHOT_LIST`（默认 false）隐藏；组件保留
- 后端：所有 `/api/video/chapter-workflows/*` 端点**保留**（旧项目打开、合片、导出仍走它）
- 不删除任何 shot 数据

### 3.3 动态时长的协议

拆分 JSON 的每个视频单元新增字段：

```json
{
  "title": "单元名",
  "summary": "剧情概要",
  "video_prompt": "三段式视频 prompt",
  "duration_seconds": 7,
  "duration_reason": "单场景双人物对话，信息密度中等",
  "dialogue": [...]
}
```

Prompt 约束改为：
- ❌ 删除："固定时长为 {duration_seconds} 秒"、"时间总和必须严格等于"、"信息不足必须补足"
- ✅ 新增："根据每个视频单元的信息密度给出 3-15 秒的建议时长；单一动作/对话 3-6 秒，双 beats 6-10 秒，复杂场面 10-15 秒；宁短勿水，禁止为凑时长添加空镜"

**档位归一化**（提交前，后端函数）：

```python
def normalize_video_duration(seconds: int, capabilities: dict) -> int:
    """归一到上游实际支持档位；档位来自 video_capabilities 配置，不硬编码。"""
```

- 档位来源：`video_capabilities`（管理后台已有模型能力配置体系）
- 归一策略：就近档位；Seedance 1.x 强制 ≤12
- 落点：`video_canvas_runtime` 提交前 + `video_chapter_pipeline`（旧链路同步受益）

### 3.4 剧本拆分在画布上的呈现

- `screenplay` 节点类型从 legacy 提回公开 NODE_CATALOG（label「剧本」，含「AI 拆分」动作按钮）
- 拆分成功 → 生成 N 个 `video` 节点，自动网格布局（每行 4 个，横向时间序，行间距 120px），与剧本节点自动连线
- video 节点属性面板展示：title/summary/prompt/duration（可手动改）/duration_reason
- 拆分走 pending-changes 确认流（与 Agent 写画布同一套机制，可回滚）

### 3.5 画布 Agent 对话创作剧本

- 扩展 `canvas_screenplay_director`：新增工具 `draft_screenplay`（对话式生成/修改剧本全文，仅返回文本，不直接写图）
- 流程：用户对话 → Agent 给出剧本草稿 → 用户说"放到画布" → Agent 调 `apply_canvas_ops` 创建/更新剧本节点（走确认）
- System prompt 注入写作规范：沿用 `build_agent_chapter_system_prompt(db)` 的质量规则（AGENTS.md 陷阱 18 红线），按剧本体裁裁剪

### 3.6 漫剧工作台结构

```
漫剧创作（新顶级 RouteKey: 'manga-drama'）
├── 项目列表页（story_type='video' 的卡片：封面/进度/最近编辑）
└── 画布工作台页（全屏画布 + 顶部工具栏 + 右侧 Agent 抽屉）
    ├── 画布区：CanvasSurface + 节点渲染（复用）
    ├── 顶部：项目名 / 保存状态 / 校验 / 运行全部 / 合片 / 导出
    └── 右侧：Agent 对话抽屉（画布上下文感知）
```

- 路由：新增 `RouteKey`（App.tsx 三步走：api.ts 类型 → 组件 → 路由分支，遵循 AGENTS.md 陷阱 7）
- 旧小说工作台的 video 模式 Tab 保留但加"建议使用漫剧创作"提示

### 3.7 【v2 新增】小说章节导入 → 剧本编辑 → 拆分工作流

#### 3.7.1 现状与差距

现有画布 plan 流**已支持** `chapter` 来源（`_resolve_canvas_source_snapshot` 会重读章节正文并计算 `source_hash`，拒绝客户端伪造），但有两个硬限制：

1. **章节必须属于画布所属作品**：`chapter.story_id != canvas.story_id` 直接拒绝。而新需求是漫剧项目（独立 story）要能选**用户名下任意小说作品**的章节。
2. **章节正文是"只读来源"**：现有 plan 流把章节正文当冻结快照直接喂给 AI 生成剧本，**用户无法在拆分前修改剧本内容**。

#### 3.7.2 设计：章节作为「剧本素材」导入，而非「执行来源」绑定

核心思路：**把"章节来源"和"剧本内容"解耦**。章节正文导入后落进画布剧本节点，从此剧本节点就是唯一事实源（用户可编辑、Agent 可改写），拆分只认剧本节点内容。章节本身只保留溯源信息（story_id/chapter_id/标题/hash），用于属性面板展示"来自《xxx》第 N 章"。

这样做的好处：
- **规避跨作品授权难题**：导入是一次性动作（选章时校验所有权），导入后画布与原作品再无运行时耦合，`chapter.story_id == canvas.story_id` 的既有校验**一行不用改**
- **剧本可编辑天然成立**：导入的正文只是剧本节点的初始内容，后续编辑/再拆分与其他剧本来源（对话创作/手动粘贴）完全同构
- 原小说作品的章节正文**绝不被修改**（漫剧只读引用，写回原作品不在本期范围）

#### 3.7.3 交互流程

```
新建漫剧项目（或画布内「添加剧本」）
   │ 选择「从小说作品导入」
   ▼
章节选择器（弹层）
   ├─ 左栏：用户名下所有 story_type='novel' 的作品列表
   │        （复用 /api/stories 列表，前端过滤；后端新接口直返 novel 类型亦可）
   └─ 右栏：选中作品的章节列表（标题/字数/更新时间；支持多选 + 拖拽排序）
   │  确认导入
   ▼
后端 IMPORT-SPLIT 服务（单次 AI 调用，可配置跳过）：
   1. 逐章读取正文（校验 owner + story_type='novel'）
   2. 正文 → 漫剧剧本体裁改写（小说叙述 → 场景头/动作行/对白）
      —— 这是"改编"不是"拆分"，输出完整剧本而非视频单元
   3. 返回剧本草稿（含来源章节清单）
   ▼
剧本节点写入画布（pending-change 确认）：
   config.content = 改写后的剧本文本
   config.source_refs = [{story_id, chapter_id, title, hash}]  ← 溯源
   │
   ▼
┌─ 剧本编辑回路（所有来源共用）────────────────┐
│  用户直接编辑节点文本（双击节点 → 行内编辑器）      │
│  或对话让 Agent 修改（draft_screenplay 工具）     │
│  每次保存 → 剧本节点 config.content 更新 + 版本化  │
└──────────────────────────────────────────┘
   │ 点「拆分」
   ▼
screenplay-split（复用现有拆分模块 + 动态时长，见 §3.3/§3.4）
   → 拆分前重算剧本内容 hash，与节点上次的 hash 比对
   → 剧本已变更则提示"剧本已修改，将按最新内容拆分"（旧拆分自动失效）
```

#### 3.7.4 技术落点

| # | 改动 | 文件 | 说明 |
|---|------|------|------|
| T1 | 章节选择数据接口：`GET /api/manga-drama/importable-stories`（用户名下 novel 作品）+ 复用 `GET /api/stories/{id}/chapters` | `routers/video_canvas.py` 或独立 router | 前端选择器数据源；只读，无跨作品写风险 |
| T2 | `POST /api/video-canvas/canvases/{id}/import-screenplay`：body `{sources:[{story_id,chapter_id}...]}` → 校验所有权 → 逐章读正文 → AI 改写成剧本 → pending-change 返回 | `routers/video_canvas.py` + `deepseek.py` 新函数 `adapt_novel_to_screenplay()` | 服务端重读正文（不信客户端内容，对齐现有 `_resolve_plan_source_snapshot` 安全模式）；正文超长时按章节分批改写后拼接 |
| T3 | 剧本节点 config 协议扩展：`content` + `source_refs` + `content_hash` | `routers/video_canvas.py`（NODE_CATALOG + 校验） | hash 用于"剧本已变更"检测 |
| T4 | 剧本节点行内编辑器（双击进入 textarea，Esc/✓ 保存） | `CanvasNodeView.tsx` | 所有文本类节点可复用 |
| T5 | screenplay-split 前置校验：重算 hash → 比对 → 过期提示 | `routers/video_canvas.py` | |
| T6 | `adapt_novel_to_screenplay` 的 prompt（小说→剧本改写规范，注入剧本体裁 + 写作质量红线） | `video_chapter_prompts.py` | |
| T7 | 测试：导入所有权校验（选他人作品章节必须 403/422）、多章节拼接、改写 JSON 解析、hash 过期检测 | `tests/` | |

#### 3.7.5 与现有 plan 流的关系

- **不改不拆**现有 `create_canvas_plan` 的 chapter 来源链路（旧画布仍在用）
- 新流程走独立端点（T2），产物直接是画布剧本节点，比 plan 流更轻
- canvas_screenplay_director 的 `resolve_canvas_source` 增加 `source_type="novel_chapter"`（跨作品只读枚举），供 Agent 对话中用户说"把《xxx》第3章改编成剧本"时使用——服务端同样只读校验 + 一次性导入语义

#### 3.7.6 权限与安全红线

- 章节选择器只列**当前登录用户自己**的作品（`owner_user_id == user.id`），无协作/共享场景
- 导入是纯读取原作品 + 写入漫剧画布，**不触碰原作品任何数据**
- `source_refs` 中的章节被原作者删除/清空后，画布剧本节点不受影响（内容已落盘，溯源仅展示用）
- 计费：改写按文本 AI 调用计费（复用 begin_ai_call 埋点，modality=text）

---

## 4. 实施计划（6 个阶段，每阶段独立可验证）

> 每阶段完成 = 后端 pytest 全绿 + 前端 `npm run build` 零错误 + 该阶段验收项通过。全程在 codex 分支，不合 pro。

### 阶段 0：分支地基（0.5 天）

| 任务 | 文件 |
|------|------|
| rebase codex → 最新 pro，解决 3 文件冲突 + submodule 指针 | `main.py` `agent_router.py` `VideoStoryboardLayout.tsx` `infinite-canvas` |
| 冲突解决原则：双方保留（pro 的新 import + codex 的 canvas import 合并） | |
| 全量验证：backend pytest + frontend build | |

**验收**：两套构建全绿；画布页在最新 pro 代码上可打开可保存。

### 阶段 1：漫剧独立菜单 + 项目类型（1 天）

| 任务 | 文件 |
|------|------|
| `stories.story_type` 增量迁移（幂等，默认 `novel`） | `models.py` `database.py` |
| 新 RouteKey `manga-drama`：项目列表页 + 画布工作台空壳 | `frontend/src/api.ts` `App.tsx` 新组件 `MangaDramaListPage.tsx` |
| 新建漫剧项目 → 创建 `story_type='video'` 的 story + 空白 canvas → 直接进画布 | `routers/video_canvas.py`（create 接口扩展） |
| 顶部导航加入口；小说工作台 video Tab 加迁移提示 | `App.tsx` 导航组件 |

**验收**：顶部菜单进漫剧 → 新建项目 → 落地空白画布；项目列表正确显示 video 类型项目；旧小说项目不受影响。

### 阶段 2：动态时长改造（1.5 天，后端为主）

| 任务 | 文件 |
|------|------|
| 新增 `SHOT_PARSE_DYNAMIC_SYSTEM_PROMPT`（删三硬约束，加时长建议规则） | `video_chapter_prompts.py` |
| 拆分 JSON 协议加 `duration_seconds`/`duration_reason` 字段解析 | `deepseek.py`（lite/full chunk 解析） |
| `normalize_video_duration()` + 档位配置接入 `video_capabilities` | `video_api.py` 或新 util |
| 画布运行时提交前归一化 | `video_canvas_runtime.py` |
| 故事版提示词 `{duration_seconds}` 动态值贯通（已有占位符） | `video_chapter_prompts.py` |
| 单元测试：动态拆分 JSON 解析（含缺字段兜底）、归一化边界（3/7/12/15/20s × seedance 1.x/2.x） | `tests/` |

**验收**：同一段剧本重拆，短对话产出 3-6s 单元、复杂场面 10-15s；seedance 1.x 模型提交 15s 单元被归一为 12s；pytest 全绿。

### 阶段 3：剧本节点 + 拆分→视频节点组（2 天）

| 任务 | 文件 |
|------|------|
| `screenplay` 提回公开 NODE_CATALOG（含 `screenplay` 输出端口） | `routers/video_canvas.py` |
| `POST .../screenplay-split`：读剧本节点文本 → 拆分 → 返回单元列表（不直接写图） | `routers/video_canvas.py` |
| 拆分结果 → pending-change（`video_canvas_graph` 类型）→ 确认后自动布局写入 video 节点组 + 连线 | `agent_service.py` 复用 apply_canvas_ops |
| 前端：剧本节点「AI 拆分」按钮 + 确认对话框 + video 节点属性面板（duration 可编辑） | `CanvasNodeView.tsx` `CanvasNodePropertyPanel.tsx` |
| 自动布局函数：单元列表 → 网格坐标 | `useCanvasInteractions.ts` 或新 util |

**验收**：画布放剧本节点 → 点拆分 → 确认 → 画布出现 N 个视频节点带各自时长、与剧本连线；撤销（Ctrl+Z）可整体回退；拒绝不写图。

### 阶段 3.5：【v2 新增】章节导入 + 剧本编辑回路（2 天）

> 依赖阶段 3 的剧本节点与拆分端点。对应设计 §3.7。

| 任务 | 文件 |
|------|------|
| `GET /api/manga-drama/importable-stories`：用户名下 novel 作品列表（含章节计数） | `routers/video_canvas.py` 或新 router |
| `POST .../import-screenplay`：多章节选择 → 所有权校验 → AI 改写（小说→剧本）→ pending-change | `routers/video_canvas.py` + `deepseek.adapt_novel_to_screenplay()` |
| `adapt_novel_to_screenplay` prompt：小说叙述→剧本体裁改写规范（场景头/动作行/对白），长文按章分批 | `video_chapter_prompts.py` |
| 剧本节点 config 协议：`content` + `source_refs` + `content_hash`；校验器同步 | `routers/video_canvas.py` |
| 剧本节点行内编辑器（双击编辑，保存版本化） | `CanvasNodeView.tsx` |
| screenplay-split 前置 hash 比对 + "剧本已修改"提示；旧拆分失效标记 | `routers/video_canvas.py` |
| `resolve_canvas_source` 增加 `novel_chapter` 来源（Agent 对话路径，跨作品只读导入） | `agent_service.py` |
| 前端章节选择器弹层（左作品右章节、多选排序） | 新 `ChapterImportDialog.tsx` |
| 测试：跨作品导入所有权校验、多章拼接、hash 过期检测、改写 JSON 解析 | `tests/` |

**验收**：
1. 导入路径：新建漫剧项目 → 从其他小说作品选 2 章 → 确认 → 画布出现剧本节点（内容为改写后剧本，属性面板显示来源章节）；
2. 编辑回路：手动改剧本内容 → 点拆分 → 提示按最新内容拆分；拆完再改剧本 → 旧视频节点组标记"剧本已变更"；
3. 安全校验：构造请求选**他人**作品的章节 → 422 拒绝；
4. 原小说作品章节正文零改动（DB 前后对比）。

### 阶段 4：画布 Agent 对话创作剧本（2 天）

| 任务 | 文件 |
|------|------|
| `draft_screenplay` 工具（对话生成/迭代剧本，带漫剧剧本体裁模板：场景头/动作行/对白/时长预估） | `agent_service.py` |
| `canvas_screenplay_director` 工具链扩展 + System prompt 注入写作规范（陷阱 18 红线） | `agent_service.py` `deepseek.py` |
| 前端：画布工作台右侧 Agent 抽屉（复用 AgentPanel，注入画布上下文） | 新 `CanvasAgentDrawer.tsx` 复用 AgentPanel |
| 「写入画布」动作 → apply_canvas_ops 确认流 | 同上 |

**验收**：空白画布对话"帮我写一个 3 幕的科幻漫剧剧本"→ Agent 产出剧本 → "放到画布" → 确认后剧本节点出现在画布；生成正文无破折号（质量规范生效验证）；配额正常扣减（陷阱 15：所有 AI 调用前 configure 注入）。

### 阶段 5：分镜列表下线 + 合片链路验证（1.5 天）

| 任务 | 文件 |
|------|------|
| feature flag 下线列表 Tab（默认关） | `VideoStoryboardLayout.tsx` `.env` |
| 合片验证：动态时长节点组 → concat → 输出；重点音画对齐 | 手动 + `video_compiler.py` 必要修补 |
| 旧项目回归：story 407 等既有视频工作流打开/合片/导出不受影响 | 手动 |
| 画布 18 项交互清单回归（对照 `.sisyphus/plans` 清单） | 手动 |

**验收**：新建漫剧项目全流程（对话→剧本→拆分→生成→合片→导出）走通；旧项目零回归。

### 阶段 6：文档 + 收尾（0.5 天）

- AGENTS.md 更新：新菜单、动态时长规范、feature flag 说明、新陷阱记录
- 版本 manifest bump；codex 分支推送
- **合并 pro 前 checklist**：全量 pytest、build、手动冒烟（阶段 5 验收单）、用户确认

**总工期估算：约 11 个工作日**（含阶段 3.5 的 2 天，不含用户审查等待）

---

## 5. 接口变更清单

### 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/video-canvas/canvases/{canvas_id}/screenplay-split` | 剧本节点拆分，返回视频单元列表（pending-change，不直接写图） |
| POST | `/api/video-canvas/canvases/{canvas_id}/import-screenplay` | 【v2】导入小说章节 → AI 改写为剧本 → pending-change（§3.7） |
| GET | `/api/manga-drama/importable-stories` | 【v2】用户名下可作为剧本素材的小说作品列表 |
| POST | `/api/manga-drama/projects` | 新建漫剧项目（story_type='video' + 初始画布） |
| GET | `/api/manga-drama/projects` | 漫剧项目列表 |
| — | Agent 工具 `draft_screenplay` | 对话式剧本创作 |
| — | Agent 来源类型 `novel_chapter` | 【v2】resolve_canvas_source 新增跨作品只读导入枚举 |

### 变更

| 位置 | 变更 |
|------|------|
| `NODE_CATALOG` | `screenplay` 从 legacy 提回公开目录 |
| 剧本节点 config | 【v2】新增 `source_refs` / `content_hash` 字段 |
| 拆分 prompt | 固定 15 秒 → 动态时长协议 |
| `video_capabilities` | 新增时长档位配置项（管理后台可配） |

### 不变（明确承诺）

- 全部 `/api/video/chapter-workflows/*` 端点（旧链路兼容）
- `chapter_video_shot` 表结构与数据
- 合片/导出/OSS 上传链路
- 【v2】`_resolve_canvas_source_snapshot` 现有 chapter 校验逻辑一行不改（新需求走独立导入端点）
- 【v2】原小说作品的章节正文只读，任何路径都不回写

---

## 6. 风险与对策

| # | 风险 | 等级 | 对策 |
|---|------|------|------|
| R1 | 动态时长后 concat 合片音画不同步 | 高 | 阶段 5 专项验证；`video_compiler` 按实际输出时长（而非配置时长）拼接，必要时探测视频真实 duration |
| R2 | 上游模型时长静默裁剪（AGENTS.md 已有 seedance >12s 教训） | 高 | 归一化发生在提交前 + 提交后比对返回的实际 duration，不一致记日志并回写节点 |
| R3 | 拆分 JSON 新字段旧模型不输出 | 中 | 解析层兜底：缺 `duration_seconds` 时按文本密度本地估算（字数/语速模型），缺 `duration_reason` 置空不报错 |
| R4 | rebase pro 冲突超预期 | 中 | 上次盘点冲突面 3+1 个文件，量可控；若 agent_service 冲突大，改为分批 cherry-pick |
| R5 | 画布节点过多时前端卡顿 | 中 | 拆分上限单次 30 个单元；超出提示分批；DOM 渲染已有 infinite-canvas 惰性先例 |
| R6 | 用户已在旧模式积累的项目迁移预期 | 低 | 旧项目完全可继续用；不强制迁移 |
| R7 | 【v2】长章节（万字级）改写超出单次 AI 输出限制 | 中 | `adapt_novel_to_screenplay` 按章节分批调用后拼接；单章超 8000 字再切段，沿用 `_repair_truncated_json` 兜底（陷阱 17） |
| R8 | 【v2】用户导入后原章节更新，画布剧本与原著脱节 | 低 | 设计使然：导入即解耦，剧本节点是唯一事实源；属性面板展示来源章节供用户自行回查 |
| R9 | 【v2】改写质量不稳定（小说节奏≠剧本节奏） | 中 | 改写 prompt 给出剧本体裁硬规范（场景头/动作行/对白占比）；输出走剧本编辑回路由用户终审，AI 只出草稿 |

---

## 7. 验收总单（合并 pro 前必须全过）

- [ ] 阶段 0-6 全部验收项通过（含 3.5 章节导入与编辑回路）
- [ ] `pytest` 全绿（含新增动态时长/拆分协议/归一化/跨作品导入校验用例）
- [ ] `npm run build`（tsc 严格模式）零错误
- [ ] 漫剧全流程冒烟：
  - [ ] 路径 A：新建→对话剧本→拆分→动态时长生成→合片→导出
  - [ ] 路径 B：新建→导入小说章节→改写剧本→手动编辑→再拆分→生成→合片
- [ ] 旧视频项目回归：打开/合片/导出正常
- [ ] 画布 18 项交互回归
- [ ] 【v2】原小说作品数据零改动验证（导入前后 DB 对比）
- [ ] AGENTS.md 已更新
- [ ] 用户确认合并

---

## 8. 决策记录

### 8.1 v1 决策（用户已确认：按推荐默认执行）

| # | 决策 | 结论 |
|---|------|------|
| Q1 | 漫剧项目数据定位 | ✅ 方案 A：`stories.story_type` 字段（`novel`/`video`） |
| Q2 | 分镜列表下线方式 | ✅ feature flag `VITE_ENABLE_SHOT_LIST` 默认关，不物理删除 |
| Q3 | 动态时长范围 | ✅ 3-15 秒建议区间 |
| Q4 | 单次拆分单元上限 | ✅ 30 个 |
| Q5 | 剧本体裁模板 | ✅ 漫剧短剧三幕式 |

### 8.2 v2 新增需求（用户 2026-08-28 补充）

| # | 需求 | 设计回应 |
|---|------|---------|
| N1 | 创建画布时可选用户已有小说作品章节正文作为剧本来源 | §3.7 章节导入流程（跨作品只读、一次性导入解耦） |
| N2 | 剧本拆分必须复用现有漫剧工作流的剧本拆分模块 | §3.3/§3.4：`screenplay-split` 直接复用 `split_scenes` + 动态时长 prompt，不另造拆分器 |
| N3 | 拆分前可自由修改剧本内容，按审批调整后的剧本拆分 | §3.7.3 剧本编辑回路：节点行内编辑 + Agent 改写，hash 比对保证拆分永远基于最新剧本 |
