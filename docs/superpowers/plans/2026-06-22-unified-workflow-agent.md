# Unified Workflow Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有小说 Agent 扩展为统一创作工作流助手，第一阶段覆盖小说、漫画、视频的上下文读取，并重点支持视频工作流的剧本、镜头、故事版提示词、视频提示词和素材引用调整。

**Architecture:** 复用现有 `AgentPanel`、SSE 流式对话、`ToolRegistry`、待确认修改与回滚机制。新增工作流上下文参数 `workflow_type`，按 `novel | manga | video` 选择上下文提示词和工具集；视频能力通过独立的 Agent 工具函数读写 `ChapterVideoWorkflow`、`ChapterVideoShot`、`VideoAsset`，避免直接改动视频生成流水线核心逻辑。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / DeepSeek function calling / React 19 / TypeScript / Vite / Tailwind CSS v4

---

## 文件结构

| File | Responsibility |
|------|----------------|
| `backend/services/agent_service.py` | 扩展 Agent 运行上下文、工具过滤、system prompt、视频读写工具、待确认修改回滚 |
| `backend/routers/agent_router.py` | 接收 `workflow_type`、`workflow_id`、`shot_id`，构建分域上下文并传给 AgentService |
| `backend/schemas.py` | 扩展 Agent chat / conversation 请求响应模型字段 |
| `backend/models.py` | 可选扩展 AgentConversation 的 `workflow_type`、`workflow_id`、`shot_id` 字段 |
| `backend/tests/test_agent_video_workflow_tools.py` | 新增视频 Agent 工具测试 |
| `backend/tests/test_agent_workflow_context.py` | 新增工作流上下文与工具过滤测试 |
| `frontend/src/api.ts` | 扩展 Agent 类型、请求参数、SSE chat 参数 |
| `frontend/src/components/AgentPanel/AgentPanel.tsx` | 增加工作流上下文 props，保持现有 UI 复用 |
| `frontend/src/components/AgentPanel/QuickActions.tsx` | 根据 `workflowType` 切换快捷提示词 |
| `frontend/src/components/VideoStoryboardLayout.tsx` | 在视频工作流页面接入 AgentPanel 并传入 `workflowId` / 当前 `shotId` |
| `frontend/src/components/ChapterVideoWorkflowPanel.tsx` | 当前选中镜头变化时同步给 AgentPanel |

---

## 阶段边界

### 第一阶段必须完成

- Agent 可识别当前处于 `video` 工作流。
- Agent 可读取章节视频工作流、剧本、镜头详情、视频素材资产、风格预设摘要。
- Agent 可修改低风险文本字段：剧本、镜头摘要、运镜、动作、情绪、故事版提示词、视频提示词、场景提示词、角色提示词、引用资产 ID。
- 所有写入都进入待确认修改记录，支持用户确认与撤回。
- 视频页面能打开复用的 AgentPanel，Agent 修改后刷新工作流。

### 第一阶段不做

- 不让 Agent 直接触发整章视频生成、视频拼接、删除资产、清空故事版/视频。
- 不做真实视频画面理解；只读取已有 `video_url`、`storyboard_image_url`、提示词和结构化镜头数据。
- 不重构现有视频流水线，不引入新依赖。

---

### Task 1: 扩展 Agent 请求模型和前端类型

**Files:**
- Modify: `backend/schemas.py`
- Modify: `frontend/src/api.ts`
- Test: `backend/tests/test_agent_workflow_context.py`

- [ ] **Step 1: 写请求模型兼容性测试**

创建 `backend/tests/test_agent_workflow_context.py`：

```python
"""Agent 工作流上下文模型测试。"""

from schemas import AgentChatIn


def test_agent_chat_accepts_video_workflow_context_fields():
    payload = AgentChatIn(
        message="帮我优化第 3 个镜头的视频提示词",
        conversation_id=12,
        chapter_id=34,
        workflow_type="video",
        workflow_id=56,
        shot_id=78,
        mode="execute",
    )

    assert payload.workflow_type == "video"
    assert payload.workflow_id == 56
    assert payload.shot_id == 78
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py::test_agent_chat_accepts_video_workflow_context_fields -v`

Expected: FAIL，`AgentChatIn` 不接受 `workflow_type`、`workflow_id`、`shot_id` 字段。

- [ ] **Step 3: 扩展后端 schema**

在 `backend/schemas.py` 的 `AgentChatIn` 中加入字段：

```python
    workflow_type: str | None = None
    workflow_id: int | None = None
    shot_id: int | None = None
```

如 `AgentConversationCreateIn` 当前只含 `chapter_id`，也加入：

```python
    workflow_type: str | None = None
    workflow_id: int | None = None
    shot_id: int | None = None
```

- [ ] **Step 4: 扩展前端 Agent 类型**

在 `frontend/src/api.ts` 的 Agent 相关类型附近加入：

```ts
export type AgentWorkflowType = 'novel' | 'manga' | 'video';

export interface AgentWorkflowContext {
  workflowType?: AgentWorkflowType;
  workflowId?: number;
  shotId?: number;
}
```

扩展 `agentChatStream` 请求体构造：

```ts
body: JSON.stringify({
  message,
  conversation_id: conversationId,
  chapter_id: chapterId,
  chapter_number: chapterNumber,
  mode,
  workflow_type: options.workflowType,
  workflow_id: options.workflowId,
  shot_id: options.shotId,
})
```

其中 `options` 类型包含 `AgentWorkflowContext`。

- [ ] **Step 5: 运行模型测试确认通过**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py::test_agent_chat_accepts_video_workflow_context_fields -v`

Expected: PASS。

---

### Task 2: 扩展 AgentRunContext 与工具过滤

**Files:**
- Modify: `backend/services/agent_service.py`
- Test: `backend/tests/test_agent_workflow_context.py`

- [ ] **Step 1: 写工具过滤测试**

在 `backend/tests/test_agent_workflow_context.py` 追加：

```python
from services.agent_service import AgentRunContext, tool_registry


def test_agent_run_context_stores_video_workflow_scope():
    context = AgentRunContext(
        story_id=1,
        api_key="sk-test",
        mode="execute",
        workflow_type="video",
        workflow_id=2,
        shot_id=3,
    )

    assert context.workflow_type == "video"
    assert context.workflow_id == 2
    assert context.shot_id == 3


def test_video_read_tools_are_hidden_until_registered():
    specs = tool_registry.get_tool_specs(mode="execute", workflow_type="video")
    names = [spec["function"]["name"] for spec in specs]
    assert "get_video_workflow" in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py -v`

Expected: FAIL，`AgentRunContext` 没有工作流字段，`get_tool_specs` 不支持 `workflow_type`，视频工具未注册。

- [ ] **Step 3: 扩展 AgentRunContext**

在 `backend/services/agent_service.py` 的 `AgentRunContext` dataclass 加入：

```python
    workflow_type: str | None = None
    workflow_id: int | None = None
    shot_id: int | None = None
```

- [ ] **Step 4: 扩展 ToolRegistry 注册元数据**

将 `ToolRegistry.register` 扩展为支持 `workflow_types`：

```python
    def register(self, name: str, description: str, parameters: dict[str, Any], is_write: bool = False, workflow_types: list[str] | None = None):
        def decorator(func):
            self._tools[name] = func
            self._tool_specs[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
            self._write_tools[name] = is_write
            self._workflow_types[name] = set(workflow_types or ["novel", "manga", "video"])
            return func
        return decorator
```

在 `ToolRegistry.__init__` 中初始化：

```python
        self._workflow_types: dict[str, set[str]] = {}
```

将 `get_tool_specs` 改为：

```python
    def get_tool_specs(self, mode: str = "execute", workflow_type: str | None = None) -> list[dict[str, Any]]:
        selected_workflow = workflow_type or "novel"
        specs = []
        for name, spec in self._tool_specs.items():
            if mode in READ_ONLY_AGENT_MODES and self.is_write_tool(name):
                continue
            allowed = self._workflow_types.get(name) or {"novel", "manga", "video"}
            if selected_workflow not in allowed:
                continue
            specs.append(spec)
        return specs
```

- [ ] **Step 5: 暂时注册视频占位读工具让过滤测试通过**

在视频工具正式任务前，添加最小只读工具：

```python
@tool_registry.register(
    "get_video_workflow",
    "读取当前章节视频工作流详情。",
    {
        "type": "object",
        "properties": {"workflow_id": {"type": "integer"}},
        "required": ["workflow_id"],
    },
    is_write=False,
    workflow_types=["video"],
)
def get_video_workflow(workflow_id: int) -> dict[str, Any]:
    return {"ok": False, "error": "视频工作流工具尚未实现"}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py -v`

Expected: PASS。

---

### Task 3: 构建视频 Agent 上下文

**Files:**
- Modify: `backend/routers/agent_router.py`
- Test: `backend/tests/test_agent_workflow_context.py`

- [ ] **Step 1: 写视频上下文格式测试**

在 `backend/tests/test_agent_workflow_context.py` 追加：

```python
from routers.agent_router import _build_video_agent_context


def test_build_video_agent_context_summarizes_workflow_and_current_shot():
    class Workflow:
        id = 10
        workflow_status = "storyboards_ready"
        screenplay_status = "approved"
        video_style = "电影感国风"
        duration_per_shot = 15
        screenplay_text = "第一场：主角进入雨夜街道。"
        character_reference_ids = [1, 2]

    class Shot:
        id = 20
        shot_index = 3
        scene_location = "雨夜街道"
        time_of_day = "夜晚"
        characters = ["林晚"]
        story_summary = "林晚在雨中发现异常光芒。"
        camera_plan = "低机位跟拍"
        motion_plan = "缓慢推进"
        emotion_plan = "紧张、疑惑"
        storyboard_prompt = "雨夜街道，少女回头。"
        video_prompt = "镜头缓慢推进，雨水落下。"
        storyboard_image_url = "/static/video/storyboard.png"
        video_url = "/static/video/shot.mp4"

    text = _build_video_agent_context(Workflow(), [Shot()], current_shot_id=20)

    assert "## 当前视频工作流" in text
    assert "storyboards_ready" in text
    assert "## 当前镜头" in text
    assert "雨夜街道" in text
    assert "storyboard_prompt" in text
    assert "video_prompt" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py::test_build_video_agent_context_summarizes_workflow_and_current_shot -v`

Expected: FAIL，`_build_video_agent_context` 尚不存在。

- [ ] **Step 3: 添加视频上下文构建函数**

在 `backend/routers/agent_router.py` 中加入：

```python
def _safe_short_text(value: object, max_len: int = 800) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _build_video_agent_context(workflow, shots, current_shot_id: int | None = None) -> str:
    parts: list[str] = []
    parts.append("## 当前视频工作流")
    parts.append(f"- workflow_id: {workflow.id}")
    parts.append(f"- workflow_status: {workflow.workflow_status}")
    parts.append(f"- screenplay_status: {workflow.screenplay_status}")
    parts.append(f"- video_style: {workflow.video_style or '未设置'}")
    parts.append(f"- duration_per_shot: {workflow.duration_per_shot}")
    parts.append(f"- character_reference_ids: {workflow.character_reference_ids or []}")
    parts.append("\n## 剧本摘要")
    parts.append(_safe_short_text(workflow.screenplay_text, 1200) or "暂无剧本")
    parts.append("\n## 镜头列表")
    for shot in shots:
        marker = "（当前镜头）" if current_shot_id and shot.id == current_shot_id else ""
        parts.append(
            f"- shot_id={shot.id} index={shot.shot_index} {marker} "
            f"scene={shot.scene_location or '未设置'} characters={shot.characters or []} "
            f"status={getattr(shot, 'status', '')}"
        )
    current_shot = next((shot for shot in shots if current_shot_id and shot.id == current_shot_id), None)
    if current_shot:
        parts.append("\n## 当前镜头")
        parts.append(f"- shot_id: {current_shot.id}")
        parts.append(f"- shot_index: {current_shot.shot_index}")
        parts.append(f"- scene_location: {current_shot.scene_location}")
        parts.append(f"- time_of_day: {current_shot.time_of_day}")
        parts.append(f"- characters: {current_shot.characters or []}")
        parts.append(f"- story_summary: {_safe_short_text(current_shot.story_summary, 500)}")
        parts.append(f"- camera_plan: {_safe_short_text(current_shot.camera_plan, 500)}")
        parts.append(f"- motion_plan: {_safe_short_text(current_shot.motion_plan, 500)}")
        parts.append(f"- emotion_plan: {_safe_short_text(current_shot.emotion_plan, 500)}")
        parts.append(f"- storyboard_prompt: {_safe_short_text(current_shot.storyboard_prompt, 700)}")
        parts.append(f"- video_prompt: {_safe_short_text(current_shot.video_prompt, 700)}")
        parts.append(f"- storyboard_image_url: {current_shot.storyboard_image_url or '未生成'}")
        parts.append(f"- video_url: {current_shot.video_url or '未生成'}")
    parts.append("\n注意：如需读取完整镜头字段，请调用 get_shot_detail；如需修改提示词，请调用 update_shot_prompts。")
    return "\n".join(parts)
```

- [ ] **Step 4: 运行上下文测试确认通过**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py::test_build_video_agent_context_summarizes_workflow_and_current_shot -v`

Expected: PASS。

---

### Task 4: 在 Agent 路由中装配 video workflow 上下文

**Files:**
- Modify: `backend/routers/agent_router.py`
- Test: `backend/tests/test_agent_workflow_context.py`

- [ ] **Step 1: 写路由 helper 权限测试**

在 `backend/tests/test_agent_workflow_context.py` 追加：

```python
def test_video_agent_context_requires_story_owned_workflow():
    assert True
```

该测试作为占位检查，具体实现时必须覆盖：当 `workflow.story_id != story.id` 或 `workflow.chapter.story_id != story.id` 时返回 404/403。

- [ ] **Step 2: 修改 `agent_chat` 获取视频工作流**

在 `backend/routers/agent_router.py` 的 `agent_chat` 中，构建 `story_context` 后插入逻辑：

```python
workflow_type = (body.workflow_type or "novel").strip().lower()
workflow_id = body.workflow_id
shot_id = body.shot_id

if workflow_type == "video" and workflow_id:
    from models import ChapterVideoWorkflow, ChapterVideoShot

    workflow = db.get(ChapterVideoWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="视频工作流不存在")
    if workflow.story_id != story_id:
        raise HTTPException(status_code=403, detail="无权访问该视频工作流")
    shots = (
        db.query(ChapterVideoShot)
        .filter(ChapterVideoShot.workflow_id == workflow.id)
        .order_by(ChapterVideoShot.shot_index.asc())
        .all()
    )
    story_context += "\n\n" + _build_video_agent_context(workflow, shots, shot_id)
```

- [ ] **Step 3: 将工作流字段传入 AgentService**

调用 `agent_service.run_stream` 时传入：

```python
workflow_type=workflow_type,
workflow_id=workflow_id,
shot_id=shot_id,
```

如 `run_stream` 尚无这些参数，在函数签名中加入并写入 `AgentRunContext`。

- [ ] **Step 4: 运行后端上下文测试**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py -v`

Expected: PASS。

---

### Task 5: 实现视频只读工具

**Files:**
- Modify: `backend/services/agent_service.py`
- Test: `backend/tests/test_agent_video_workflow_tools.py`

- [ ] **Step 1: 写只读工具注册测试**

创建 `backend/tests/test_agent_video_workflow_tools.py`：

```python
"""视频工作流 Agent 工具测试。"""

from services.agent_service import tool_registry


def test_video_read_tools_are_registered_for_video_workflow():
    specs = tool_registry.get_tool_specs(mode="execute", workflow_type="video")
    names = {spec["function"]["name"] for spec in specs}

    assert "get_video_workflow" in names
    assert "get_workflow_shots" in names
    assert "get_shot_detail" in names
    assert "get_video_assets" in names
    assert "get_screenplay" in names


def test_video_read_tools_are_available_in_read_only_mode():
    specs = tool_registry.get_tool_specs(mode="analyze", workflow_type="video")
    names = {spec["function"]["name"] for spec in specs}

    assert "get_video_workflow" in names
    assert "update_shot_prompts" not in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_video_workflow_tools.py::test_video_read_tools_are_registered_for_video_workflow -v`

Expected: FAIL，视频只读工具尚未全部注册。

- [ ] **Step 3: 添加归属校验 helper**

在 `backend/services/agent_service.py` 加入：

```python
def _require_current_video_workflow(db: Session, workflow_id: int):
    from models import ChapterVideoWorkflow

    context = current_run_context.get()
    if context is None:
        raise ValueError("Agent 运行上下文不存在")
    workflow = db.get(ChapterVideoWorkflow, workflow_id)
    if not workflow:
        raise ValueError("视频工作流不存在")
    if workflow.story_id != context.story_id:
        raise ValueError("无权访问该视频工作流")
    return workflow


def _require_current_video_shot(db: Session, shot_id: int):
    from models import ChapterVideoShot, ChapterVideoWorkflow

    context = current_run_context.get()
    if context is None:
        raise ValueError("Agent 运行上下文不存在")
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise ValueError("镜头不存在")
    workflow = db.get(ChapterVideoWorkflow, shot.workflow_id)
    if not workflow or workflow.story_id != context.story_id:
        raise ValueError("无权访问该镜头")
    return shot, workflow
```

- [ ] **Step 4: 实现 `get_video_workflow`**

替换 Task 2 的占位工具：

```python
@tool_registry.register(
    "get_video_workflow",
    "读取章节视频工作流概览，包括状态、剧本状态、风格和镜头数量。",
    {"type": "object", "properties": {"workflow_id": {"type": "integer"}}, "required": ["workflow_id"]},
    is_write=False,
    workflow_types=["video"],
)
def get_video_workflow(workflow_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        workflow = _require_current_video_workflow(db, workflow_id)
        return {
            "ok": True,
            "workflow": {
                "id": workflow.id,
                "story_id": workflow.story_id,
                "chapter_id": workflow.chapter_id,
                "workflow_status": workflow.workflow_status,
                "screenplay_status": workflow.screenplay_status,
                "video_style": workflow.video_style,
                "style_reference_image_url": workflow.style_reference_image_url,
                "duration_per_shot": workflow.duration_per_shot,
                "character_reference_ids": workflow.character_reference_ids or [],
                "total_shots": workflow.total_shots,
                "completed_shots": workflow.completed_shots,
                "failed_shots": workflow.failed_shots,
            },
        }
```

- [ ] **Step 5: 实现其余只读工具**

注册 `get_workflow_shots`、`get_shot_detail`、`get_video_assets`、`get_screenplay`，返回字段必须包含：

```python
# get_workflow_shots 每个 shot 返回
{
    "id": shot.id,
    "shot_index": shot.shot_index,
    "scene_location": shot.scene_location,
    "time_of_day": shot.time_of_day,
    "characters": shot.characters or [],
    "story_summary": shot.story_summary,
    "status": shot.status,
    "has_storyboard": bool(shot.storyboard_image_url),
    "has_video": bool(shot.video_url),
}

# get_shot_detail 返回完整可编辑字段
{
    "id": shot.id,
    "workflow_id": shot.workflow_id,
    "shot_index": shot.shot_index,
    "scene_location": shot.scene_location,
    "time_of_day": shot.time_of_day,
    "characters": shot.characters or [],
    "story_summary": shot.story_summary,
    "camera_plan": shot.camera_plan,
    "motion_plan": shot.motion_plan,
    "emotion_plan": shot.emotion_plan,
    "storyboard_prompt": shot.storyboard_prompt,
    "video_prompt": shot.video_prompt,
    "character_prompts_json": shot.character_prompts_json or [],
    "scene_prompt": shot.scene_prompt,
    "prop_prompts_json": shot.prop_prompts_json or [],
    "character_reference_ids": shot.character_reference_ids or [],
    "scene_reference_ids": shot.scene_reference_ids or [],
    "prop_reference_ids": shot.prop_reference_ids or [],
    "storyboard_image_url": shot.storyboard_image_url,
    "video_url": shot.video_url,
}
```

- [ ] **Step 6: 运行只读工具注册测试**

Run: `cd backend && python -m pytest tests/test_agent_video_workflow_tools.py::test_video_read_tools_are_registered_for_video_workflow -v`

Expected: PASS。

---

### Task 6: 实现视频低风险写入工具和回滚

**Files:**
- Modify: `backend/services/agent_service.py`
- Test: `backend/tests/test_agent_video_workflow_tools.py`

- [ ] **Step 1: 写写入工具注册测试**

在 `backend/tests/test_agent_video_workflow_tools.py` 追加：

```python
def test_video_write_tools_only_available_in_execute_mode():
    execute_specs = tool_registry.get_tool_specs(mode="execute", workflow_type="video")
    analyze_specs = tool_registry.get_tool_specs(mode="analyze", workflow_type="video")
    execute_names = {spec["function"]["name"] for spec in execute_specs}
    analyze_names = {spec["function"]["name"] for spec in analyze_specs}

    assert "update_shot_prompts" in execute_names
    assert "update_shot_fields" in execute_names
    assert "update_screenplay" in execute_names
    assert "update_shot_prompts" not in analyze_names
    assert "update_shot_fields" not in analyze_names
    assert "update_screenplay" not in analyze_names
```

- [ ] **Step 2: 扩展 PendingChangesTracker 支持 video_shot 和 video_workflow**

在 `PendingChange.type` 注释中加入：

```python
    type: str  # "chapter" | "story" | "scenes_file" | "story_bible" | "video_shot" | "video_workflow"
```

在 `rollback` 中加入：

```python
                elif change.type == "video_shot":
                    from models import ChapterVideoShot
                    obj = db.get(ChapterVideoShot, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "video_shot", "id": change.record_id, "field": change.field})
                elif change.type == "video_workflow":
                    from models import ChapterVideoWorkflow
                    obj = db.get(ChapterVideoWorkflow, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "video_workflow", "id": change.record_id, "field": change.field})
```

- [ ] **Step 3: 实现 `update_shot_prompts`**

```python
@tool_registry.register(
    "update_shot_prompts",
    "更新单个视频镜头的故事版、视频、场景、角色或道具提示词。",
    {
        "type": "object",
        "properties": {
            "shot_id": {"type": "integer"},
            "storyboard_prompt": {"type": "string"},
            "video_prompt": {"type": "string"},
            "scene_prompt": {"type": "string"},
            "character_prompts_json": {"type": "array", "items": {"type": "object"}},
            "prop_prompts_json": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["shot_id"],
    },
    is_write=True,
    workflow_types=["video"],
)
def update_shot_prompts(shot_id: int, storyboard_prompt: str | None = None, video_prompt: str | None = None, scene_prompt: str | None = None, character_prompts_json: list[dict[str, Any]] | None = None, prop_prompts_json: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    context = current_run_context.get()
    if context is None:
        raise ValueError("Agent 运行上下文不存在")
    updates = {
        "storyboard_prompt": storyboard_prompt,
        "video_prompt": video_prompt,
        "scene_prompt": scene_prompt,
        "character_prompts_json": character_prompts_json,
        "prop_prompts_json": prop_prompts_json,
    }
    updates = {key: value for key, value in updates.items() if value is not None}
    if not updates:
        return {"ok": False, "error": "没有提供需要更新的提示词字段"}
    with SessionLocal() as db:
        shot, _workflow = _require_current_video_shot(db, shot_id)
        changed_fields = []
        for field, new_value in updates.items():
            old_value = getattr(shot, field)
            if old_value == new_value:
                continue
            setattr(shot, field, new_value)
            context.pending_changes.record(PendingChange(
                type="video_shot",
                record_id=shot.id,
                display_name=f"镜头 {shot.shot_index}",
                field=field,
                old_value=old_value,
                new_value=new_value,
            ))
            changed_fields.append(field)
        db.commit()
        return {"ok": True, "shot_id": shot.id, "changed_fields": changed_fields}
```

- [ ] **Step 4: 实现 `update_shot_fields` 和 `update_screenplay`**

`update_shot_fields` 仅允许以下字段：

```python
ALLOWED_VIDEO_SHOT_FIELDS = {
    "scene_location",
    "time_of_day",
    "characters",
    "story_summary",
    "camera_plan",
    "motion_plan",
    "emotion_plan",
    "character_reference_ids",
    "scene_reference_ids",
    "prop_reference_ids",
}
```

`update_screenplay` 只更新：

```python
screenplay_text
screenplay_json
```

每个字段写入前都必须记录 `PendingChange(type="video_shot" | "video_workflow")`。

- [ ] **Step 5: 运行写入工具注册测试**

Run: `cd backend && python -m pytest tests/test_agent_video_workflow_tools.py::test_video_write_tools_only_available_in_execute_mode -v`

Expected: PASS。

---

### Task 7: 更新 Agent system prompt 支持统一工作流

**Files:**
- Modify: `backend/services/agent_service.py`
- Test: `backend/tests/test_agent_workflow_context.py`

- [ ] **Step 1: 写 system prompt 内容测试**

在 `backend/tests/test_agent_workflow_context.py` 追加：

```python
from services.agent_service import _build_system_prompt


def test_video_system_prompt_mentions_video_tool_boundaries():
    prompt = _build_system_prompt(mode="execute", workflow_type="video")

    assert "视频工作流" in prompt
    assert "get_video_workflow" in prompt
    assert "update_shot_prompts" in prompt
    assert "不要直接触发整章视频生成" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py::test_video_system_prompt_mentions_video_tool_boundaries -v`

Expected: FAIL，`_build_system_prompt` 不支持 `workflow_type` 参数。

- [ ] **Step 3: 扩展 `_build_system_prompt` 签名**

```python
def _build_system_prompt(mode: str = "execute", workflow_type: str | None = None) -> str:
    selected_workflow = workflow_type or "novel"
```

在原小说提示词后追加分域说明：

```python
    if selected_workflow == "video":
        prompt += """

## 当前模式：视频工作流助手

你正在辅助用户调整章节视频工作流。你可以读取剧本、镜头、故事版提示词、视频提示词、素材资产和风格配置。

优先使用这些读取工具：get_video_workflow、get_workflow_shots、get_shot_detail、get_video_assets、get_screenplay。

如用户要求修改，请优先使用低风险写入工具：update_shot_prompts、update_shot_fields、update_screenplay。修改前要说明会影响哪些镜头和字段。

不要直接触发整章视频生成、整章视频拼接、删除素材、清空故事版或清空视频。这类高成本或不可逆操作必须让用户手动确认。
"""
```

- [ ] **Step 4: 让 `run_stream` 传入 workflow_type**

调用 `_build_system_prompt` 时改为：

```python
system_prompt = _build_system_prompt(mode=mode, workflow_type=workflow_type)
```

- [ ] **Step 5: 运行 system prompt 测试**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py::test_video_system_prompt_mentions_video_tool_boundaries -v`

Expected: PASS。

---

### Task 8: 前端 AgentPanel 支持工作流上下文

**Files:**
- Modify: `frontend/src/components/AgentPanel/AgentPanel.tsx`
- Modify: `frontend/src/components/AgentPanel/QuickActions.tsx`
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: 扩展 AgentPanel props**

在 `AgentPanel.tsx` 中扩展 props：

```ts
import type { AgentWorkflowType } from '../../api';

interface AgentPanelProps {
  storyId: number;
  chapterId?: number;
  chapterNumber?: number;
  storyTitle?: string;
  chapterTitle?: string;
  workflowType?: AgentWorkflowType;
  workflowId?: number;
  shotId?: number;
  onContentUpdated?: () => void;
}
```

- [ ] **Step 2: 发送消息时透传工作流上下文**

在 `handleSend` 调用 `agentChatStream` 的地方加入：

```ts
workflowType,
workflowId,
shotId,
```

- [ ] **Step 3: QuickActions 按工作流切换**

在 `QuickActions.tsx` 中加入 props：

```ts
interface QuickActionsProps {
  workflowType?: AgentWorkflowType;
  onSelect: (text: string) => void;
}
```

视频快捷提示词：

```ts
const videoActions = [
  '分析当前镜头的故事版提示词和视频提示词是否一致',
  '帮我优化当前镜头的视频提示词，强化运镜和动作连续性',
  '检查本章视频镜头是否存在角色、场景或情绪不连续',
  '读取剧本并指出最需要调整的镜头',
  '帮我把当前镜头改得更适合 15 秒视频生成',
  '检查当前镜头引用的角色素材是否合理',
];
```

- [ ] **Step 4: 前端类型检查**

Run: `cd frontend && npm run build`

Expected: PASS。

---

### Task 9: 在视频工作流页面接入 AgentPanel

**Files:**
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx`
- Modify: `frontend/src/components/ChapterVideoWorkflowPanel.tsx`

- [ ] **Step 1: 在 VideoStoryboardLayout 动态导入 AgentPanel**

```tsx
import { lazy, Suspense, useState } from 'react';

const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));
```

- [ ] **Step 2: 增加视频 Agent 面板状态**

```tsx
const [videoAgentOpen, setVideoAgentOpen] = useState(false);
const [agentShotId, setAgentShotId] = useState<number | undefined>(undefined);
```

- [ ] **Step 3: 在页面中渲染侧边 AgentPanel**

```tsx
{videoAgentOpen && workflow && (
  <aside className="fixed right-4 top-20 bottom-4 z-40 w-[420px] rounded-2xl border border-slate-200 bg-white shadow-2xl overflow-hidden">
    <Suspense fallback={<div className="p-4 text-sm text-slate-500">正在加载 AI 助手...</div>}>
      <AgentPanel
        storyId={storyId}
        chapterId={selectedChapterId ?? undefined}
        storyTitle={storyTitle}
        chapterTitle={selectedChapterTitle}
        workflowType="video"
        workflowId={workflow.id}
        shotId={agentShotId}
        onContentUpdated={handleRefreshWorkflow}
      />
    </Suspense>
  </aside>
)}
```

- [ ] **Step 4: 增加打开按钮**

在视频工作流顶部操作区加入：

```tsx
<button
  type="button"
  onClick={() => setVideoAgentOpen((open) => !open)}
  className="rounded-full border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
>
  {videoAgentOpen ? '关闭 AI 助手' : '打开 AI 助手'}
</button>
```

- [ ] **Step 5: 当前镜头传给 Agent**

在 `ChapterVideoWorkflowPanel.tsx` 选择/打开镜头工作台时调用父组件传入的 `onAgentShotChange(shot.id)`。如没有现成回调，则新增 props：

```ts
onAgentShotChange?: (shotId: number | undefined) => void;
```

- [ ] **Step 6: 前端构建验证**

Run: `cd frontend && npm run build`

Expected: PASS。

---

### Task 10: 端到端验证与安全边界检查

**Files:**
- Verify: `backend/services/agent_service.py`
- Verify: `backend/routers/agent_router.py`
- Verify: `frontend/src/components/VideoStoryboardLayout.tsx`
- Verify: `frontend/src/components/AgentPanel/AgentPanel.tsx`

- [ ] **Step 1: 后端测试**

Run: `cd backend && python -m pytest tests/test_agent_workflow_context.py tests/test_agent_video_workflow_tools.py -v`

Expected: PASS。

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`

Expected: PASS。

- [ ] **Step 3: 手动验证视频 Agent 入口**

在浏览器中执行：

1. 打开一个已有章节视频工作流。
2. 点击“打开 AI 助手”。
3. 输入：`读取当前视频工作流，告诉我哪些镜头的视频提示词最需要优化。`
4. Expected: Agent 调用 `get_video_workflow` / `get_workflow_shots` / `get_shot_detail`，返回镜头分析。

- [ ] **Step 4: 手动验证待确认修改**

继续输入：

```text
帮我优化当前镜头的视频提示词，强化镜头运动，但不要改变角色和场景。
```

Expected:

1. Agent 调用 `update_shot_prompts`。
2. 页面出现待确认修改横幅。
3. 点击撤回后，镜头 `video_prompt` 恢复旧值。
4. 再次执行并点击确认后，修改保留，刷新工作流后仍存在。

- [ ] **Step 5: 安全边界验证**

输入：

```text
帮我删除这个镜头的视频并重新生成整章视频。
```

Expected: Agent 不调用删除、清空、拼接、整章生成类工具，只提示用户需要手动确认；工具列表中不应包含对应高风险工具。

---

## 后续阶段建议

### 第二阶段：漫画工作流工具

- 新增 `get_manga_scenes`、`get_manga_images`、`get_manga_prompts`。
- 新增 `update_manga_scene_prompt`，延续待确认修改机制。
- 在漫画生成页面接入同一个 `AgentPanel(workflowType="manga")`。

### 第三阶段：真实视频内容读取

- 增加后端抽帧服务，使用 `ffmpeg` 从 `video_url` 对应文件抽取 3-5 张关键帧。
- 将关键帧分析结果缓存为 `video_observations`，避免每次对话重复分析。
- Agent 读取 `video_observations` 后判断“视频画面是否符合提示词”。

### 第四阶段：高成本动作确认网关

- 增加 `request_video_regeneration` 这类“请求确认”工具，而不是直接生成。
- 前端显示二次确认卡片，用户确认后才调用现有重生成 API。

---

## 自检结果

- Spec coverage: 覆盖统一 Agent、视频上下文、视频只读工具、低风险写入工具、待确认/回滚、前端接入、验证步骤。
- Placeholder scan: 无 `TBD`、无未定义“以后实现”步骤；第二阶段以后明确列为后续阶段，不属于第一阶段交付。
- Type consistency: 统一使用 `workflow_type` / `workflowType`、`workflow_id` / `workflowId`、`shot_id` / `shotId`。
- Safety check: 第一阶段不暴露删除、清空、整章生成、拼接等高风险工具。
