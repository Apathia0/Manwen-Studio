# 漫剧创作画布化改造开发文档

> 分支：`codex/video-canvas-three-node`（在 codex 分支开发，测试通过后合入 `pro`）
> 状态：**待审查** — 本文档为实施蓝图，未经确认不写任何业务代码
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

---

## 2. 目标架构

### 2.1 用户旅程（改造后）

```
顶部导航「漫剧创作」（独立菜单，不再藏于小说工作台）
   │
   ▼
漫剧项目列表（story 的 video 子集或独立 project 概念，见 §3.1 决策）
   │ 新建项目
   ▼
空白画布页（默认挂一个文本节点 + Agent 面板展开）
   │
   ▼
用户与画布 Agent 对话 → Agent 生成剧本 → 确认后写入画布「剧本」节点
   │  用户点击剧本节点的「拆分」动作（或对话指令）
   ▼
后端按剧本内容动态拆分 → 每个视频单元带建议时长（3-15s）+ 密度理由
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

**总工期估算：约 9 个工作日**（不含用户审查等待）

---

## 5. 接口变更清单

### 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/video-canvas/canvases/{canvas_id}/screenplay-split` | 剧本节点拆分，返回视频单元列表（pending-change，不直接写图） |
| POST | `/api/manga-drama/projects` | 新建漫剧项目（story_type='video' + 初始画布） |
| GET | `/api/manga-drama/projects` | 漫剧项目列表 |
| — | Agent 工具 `draft_screenplay` | 对话式剧本创作 |

### 变更

| 位置 | 变更 |
|------|------|
| `NODE_CATALOG` | `screenplay` 从 legacy 提回公开目录 |
| 拆分 prompt | 固定 15 秒 → 动态时长协议 |
| `video_capabilities` | 新增时长档位配置项（管理后台可配） |

### 不变（明确承诺）

- 全部 `/api/video/chapter-workflows/*` 端点（旧链路兼容）
- `chapter_video_shot` 表结构与数据
- 合片/导出/OSS 上传链路

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

---

## 7. 验收总单（合并 pro 前必须全过）

- [ ] 阶段 0-5 全部验收项通过
- [ ] `pytest` 全绿（含新增动态时长/拆分协议/归一化用例）
- [ ] `npm run build`（tsc 严格模式）零错误
- [ ] 漫剧全流程冒烟：新建→对话剧本→拆分→动态时长生成→合片→导出
- [ ] 旧视频项目回归：打开/合片/导出正常
- [ ] 画布 18 项交互回归
- [ ] AGENTS.md 已更新
- [ ] 用户确认合并

---

## 8. 待用户确认的决策点

| # | 决策 | 默认方案 | 备选 |
|---|------|---------|------|
| Q1 | 漫剧项目数据定位 | §3.1 方案 A（story_type 字段） | 方案 B（新表） |
| Q2 | 分镜列表下线方式 | §3.2 feature flag 默认关 | 物理删除入口 |
| Q3 | 动态时长范围 | 3-15 秒建议区间 | 更宽（如 2-20s，需确认上游档位） |
| Q4 | 单次拆分单元上限 | 30 个 | 20 / 50 |
| Q5 | 剧本体裁模板 | 漫剧短剧三幕式 | 是否需要其他体裁选项 |
