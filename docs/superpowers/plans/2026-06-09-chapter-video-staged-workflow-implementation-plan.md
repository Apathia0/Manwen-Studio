# 章节视频分阶段工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将章节视频工作流从默认一键全自动改为默认分阶段手动控制，保留一键全自动辅助入口，并修复 Image2 401 鉴权错误。

**Architecture:** 保留现有 `ChapterVideoWorkflow` / `ChapterVideoShot` 数据模型与现有视频工作台页面骨架，把后端工作流拆成“拆镜 / 故事版 / 视频 / 拼接”四个独立阶段接口；一键模式仅作为对这些阶段接口的顺序包装。前端以阶段控制为主，支持镜头勾选、故事版 prompt 编辑、重新分析与失败重试。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、PostgreSQL、Pydantic v2、React 19、TypeScript、Vite、pytest

---

## File Structure

### Backend

- Modify: `backend/models.py`
  - 扩展 `ChapterVideoWorkflow` 的阶段状态字段定义与必要的工作流元数据
- Modify: `backend/schemas.py`
  - 增加阶段操作请求/响应 schema
- Modify: `backend/database.py`
  - 增加章节视频工作流阶段字段与状态长度迁移
- Modify: `backend/services/video_chapter_pipeline.py`
  - 将一键协程拆分为可独立调用的阶段函数
  - 修复 DeepSeek / Image2 key 分离
- Modify: `backend/services/deepseek.py`
  - 增加“重新分析故事版 prompt”的辅助函数或复用现有 prompt 生成入口
- Modify: `backend/routers/video.py`
  - 新增阶段性 API：仅拆镜、批量故事版、批量视频、一键全自动、重分析 prompt
- Create: `backend/tests/test_video_chapter_stage_api.py`
  - 覆盖阶段接口行为、鉴权 key 分离、失败停阶段行为
- Modify: `backend/tests/test_video_chapter_pipeline.py`
  - 覆盖阶段状态流转与长度约束
- Modify: `backend/tests/test_video_chapter_workflow_api.py`
  - 覆盖创建入口、迁移兜底和 detached/session 行为

### Frontend

- Modify: `frontend/src/api.ts`
  - 增加阶段性请求 API 与请求/响应类型
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx`
  - 以阶段式主流程替换默认“一键跑到底”的交互
- Modify: `frontend/src/components/ChapterVideoWorkflowPanel.tsx`
  - 顶部工具条改造成阶段操作条
  - 增加镜头勾选、阶段按钮、错误恢复入口
- Create: `frontend/src/components/ChapterVideoPromptEditor.tsx`
  - 聚焦故事版 prompt 编辑与重新分析入口
- Reuse: `frontend/src/components/AssetReferenceSelector.tsx`
  - 继续承担角色参考图选择

### Docs

- Reference: `docs/superpowers/specs/2026-06-09-chapter-video-staged-workflow-design.md`

---

### Task 1: 后端阶段状态机与鉴权拆分

**Files:**
- Modify: `backend/models.py:353-433`
- Modify: `backend/schemas.py:875-956`
- Modify: `backend/database.py:663-742`
- Test: `backend/tests/test_video_chapter_pipeline.py`

- [ ] **Step 1: 写失败测试，锁住状态字段和阶段 schema 需求**

```python
def test_chapter_video_workflow_supports_stage_statuses():
    workflow_status_length = ChapterVideoWorkflow.__table__.c.workflow_status.type.length
    expected = [
        'pending',
        'parsing_shots',
        'shots_ready',
        'generating_storyboards',
        'storyboards_ready',
        'generating_videos',
        'videos_ready',
        'completed',
        'failed',
    ]
    assert workflow_status_length >= max(len(item) for item in expected)


def test_chapter_video_shot_status_supports_manual_stage_values():
    shot_status_length = ChapterVideoShot.__table__.c.status.type.length
    expected = [
        'pending',
        'storyboard_generating',
        'storyboard_ready',
        'video_generating',
        'video_ready',
        'failed',
    ]
    assert shot_status_length >= max(len(item) for item in expected)
```

- [ ] **Step 2: 运行测试，确认当前状态定义不足**

Run: `python -m pytest backend/tests/test_video_chapter_pipeline.py::test_chapter_video_workflow_supports_stage_statuses -q`

Expected: FAIL，提示 `workflow_status` 长度不足或阶段状态不完整

- [ ] **Step 3: 最小实现模型与 schema 变更**

```python
# backend/models.py
workflow_status: Mapped[str] = mapped_column(String(32), default="pending")

# backend/schemas.py
class ChapterWorkflowStageActionRequest(BaseModel):
    shot_ids: list[int] = []
    run_all: bool = False
    auto_continue: bool = False


class ChapterWorkflowPromptReanalyzeRequest(BaseModel):
    shot_ids: list[int] = []
```

```python
# backend/database.py
conn.execute(text("ALTER TABLE chapter_video_workflows ALTER COLUMN workflow_status TYPE VARCHAR(32)"))
conn.execute(text("ALTER TABLE chapter_video_shots ALTER COLUMN status TYPE VARCHAR(32)"))
```

- [ ] **Step 4: 运行测试，确认模型层通过**

Run: `python -m pytest backend/tests/test_video_chapter_pipeline.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/schemas.py backend/database.py backend/tests/test_video_chapter_pipeline.py
git commit -m "feat: add staged workflow status model support"
```

### Task 2: 后端将自动工作流拆成独立阶段接口

**Files:**
- Modify: `backend/services/video_chapter_pipeline.py:188-603`
- Modify: `backend/routers/video.py:5539-5750`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 写失败测试，锁住“手动模式不自动跨阶段推进”**

```python
def test_parse_stage_stops_at_shots_ready(monkeypatch):
    async def fake_parse(**kwargs):
        return [{
            'shot_index': 1,
            'source_text_span': '原文',
            'scene_location': '客厅',
            'time_of_day': '夜',
            'characters': ['林秋'],
            'story_summary': '她停下脚步',
            'dialogue_or_narration': '她没有继续向前。',
            'camera_plan': '中景',
            'motion_plan': '停步',
            'emotion_plan': '警觉',
            'continuity_notes': '保持服装一致',
        }]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'parse_chapter_to_shots', fake_parse)

    result = asyncio.run(video_chapter_pipeline.parse_chapter_shots(
        workflow_id=1,
        chapter_id=2,
        story_id=3,
        source_text='正文',
        deepseek_api_key='dk',
    ))

    assert result['workflow_status'] == 'shots_ready'
```

- [ ] **Step 2: 运行测试，确认当前后端还只有“一键跑到底”**

Run: `python -m pytest backend/tests/test_video_chapter_stage_api.py::test_parse_stage_stops_at_shots_ready -q`

Expected: FAIL，提示 `parse_chapter_shots` 不存在或返回值不符合预期

- [ ] **Step 3: 最小实现阶段函数与路由**

```python
# backend/services/video_chapter_pipeline.py
async def parse_chapter_shots(...):
    update_workflow_status(workflow_id, 'parsing_shots')
    shots_data = await deepseek_service.parse_chapter_to_shots(...)
    save_shots_from_parse(workflow_id, shots_data)
    update_workflow_status(workflow_id, 'shots_ready')
    return {'workflow_status': 'shots_ready', 'shot_count': len(shots_data)}


async def generate_storyboards_for_shots(...):
    update_workflow_status(workflow_id, 'generating_storyboards')
    # 仅处理指定 shot_ids
    # 失败后停在 generating_storyboards 或 storyboards_ready


async def generate_videos_for_shots(...):
    update_workflow_status(workflow_id, 'generating_videos')
    # 仅处理 storyboard_ready 的 shot_ids
```

```python
# backend/routers/video.py
@router.post('/api/video/chapter-workflows/{workflow_id}/parse')
async def api_parse_chapter_shots(...):
    ...


@router.post('/api/video/chapter-workflows/{workflow_id}/storyboards')
async def api_generate_storyboards(...):
    ...


@router.post('/api/video/chapter-workflows/{workflow_id}/videos')
async def api_generate_videos(...):
    ...


@router.post('/api/video/chapter-workflows/{workflow_id}/run-all')
async def api_run_all_stages(...):
    ...
```

- [ ] **Step 4: 运行测试，确认阶段接口工作**

Run: `python -m pytest backend/tests/test_video_chapter_stage_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/video_chapter_pipeline.py backend/routers/video.py backend/tests/test_video_chapter_stage_api.py
git commit -m "feat: split chapter video workflow into manual stages"
```

### Task 3: 修复 DeepSeek / Image2 key 混用导致的 401

**Files:**
- Modify: `backend/routers/video.py:143-189,5539-5750`
- Modify: `backend/services/video_chapter_pipeline.py:188-603`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 写失败测试，锁住故事版阶段必须使用 image_api_key**

```python
def test_storyboard_stage_uses_image_api_key_not_deepseek_key(monkeypatch):
    captured = {}

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    asyncio.run(video_chapter_pipeline.generate_storyboards_for_shots(
        workflow_id=1,
        story_id=2,
        shot_ids=[1],
        image_api_key='image-key',
        deepseek_api_key='deepseek-key',
    ))

    assert captured['api_key'] == 'image-key'
```

- [ ] **Step 2: 运行测试，确认当前实现仍在混用 key**

Run: `python -m pytest backend/tests/test_video_chapter_stage_api.py::test_storyboard_stage_uses_image_api_key_not_deepseek_key -q`

Expected: FAIL，当前实现会把 DeepSeek key 用在故事版生成上

- [ ] **Step 3: 最小实现 key 分离**

```python
# backend/routers/video.py
deepseek_api_key = _user_deepseek_api_key(request, db)
image_api_key = _user_image_api_key(request)

await start_workflow_background(
    wf.id,
    deepseek_api_key=deepseek_api_key,
    image_api_key=image_api_key,
)
```

```python
# backend/services/video_chapter_pipeline.py
async def generate_storyboards_for_shots(..., image_api_key: str | None = None, deepseek_api_key: str | None = None):
    storyboard_prompt = await deepseek_service.generate_shot_storyboard_prompt(..., api_key=deepseek_api_key)
    image_result = await image_service.generate_manga_image(..., api_key=image_api_key)
```

- [ ] **Step 4: 运行测试，确认 401 根因修复**

Run: `python -m pytest backend/tests/test_video_chapter_stage_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/video.py backend/services/video_chapter_pipeline.py backend/tests/test_video_chapter_stage_api.py
git commit -m "fix: separate image and deepseek keys in chapter workflow"
```

### Task 4: 前端改成分阶段主流程

**Files:**
- Modify: `frontend/src/api.ts:2672-3079`
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx:1-306`
- Modify: `frontend/src/components/ChapterVideoWorkflowPanel.tsx:1-293`
- Create: `frontend/src/components/ChapterVideoPromptEditor.tsx`

- [ ] **Step 1: 先定义新的前端 API 类型与请求函数**

```typescript
export async function parseChapterWorkflowShots(workflowId: number) {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/parse`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateChapterWorkflowStoryboards(
  workflowId: number,
  payload: { shot_ids: number[] }
) {
  ...
}

export async function generateChapterWorkflowVideos(
  workflowId: number,
  payload: { shot_ids: number[] }
) {
  ...
}

export async function reanalyzeChapterWorkflowStoryboardPrompt(
  workflowId: number,
  payload: { shot_ids: number[] }
) {
  ...
}
```

- [ ] **Step 2: 将工作台顶部主按钮拆成阶段工具条**

```tsx
<div className="flex items-center gap-2">
  <button onClick={() => void onParseShots()}>生成镜头</button>
  <button onClick={() => void onGenerateStoryboards(selectedShotIds)}>批量生成故事版</button>
  <button onClick={() => void onGenerateVideos(selectedShotIds)}>批量生成视频</button>
  <button onClick={() => void onConcatWorkflow()}>拼接成片</button>
  <button onClick={() => void onRunAll()}>一键全自动</button>
</div>
```

- [ ] **Step 3: 增加镜头勾选与故事版 prompt 编辑器**

```tsx
<input
  type="checkbox"
  checked={selectedShotIds.has(shot.id)}
  onChange={() => onToggleShot(shot.id)}
/>

<ChapterVideoPromptEditor
  value={storyboardPromptDraft[shot.id] || shot.storyboard_prompt || ''}
  onChange={(nextValue) => onChangeStoryboardPrompt(shot.id, nextValue)}
  onReanalyze={() => void onReanalyzePrompt(shot.id)}
/>
```

- [ ] **Step 4: 将失败恢复入口加到镜头卡片**

```tsx
{shot.status === 'failed' && (
  <div className="flex gap-2">
    <button onClick={() => void onReanalyzePrompt(shot.id)}>重新分析提示词</button>
    <button onClick={() => void onRegenerateStoryboard(shot.id)}>重试故事版</button>
    <button onClick={() => onSkipShot(shot.id)}>跳过此镜头</button>
  </div>
)}
```

- [ ] **Step 5: 运行前端构建验证**

Run: `npm run build`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/VideoStoryboardLayout.tsx frontend/src/components/ChapterVideoWorkflowPanel.tsx frontend/src/components/ChapterVideoPromptEditor.tsx
git commit -m "feat: add staged chapter video workflow ui"
```

### Task 5: 失败停阶段与手动继续规则

**Files:**
- Modify: `backend/services/video_chapter_pipeline.py`
- Modify: `frontend/src/components/ChapterVideoWorkflowPanel.tsx`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 写失败测试，锁住故事版失败后不自动进入视频阶段**

```python
def test_storyboard_failure_keeps_workflow_in_storyboard_stage(monkeypatch):
    async def fake_generate_manga_image(**kwargs):
        raise Exception('auth failed')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.generate_storyboards_for_shots(
        workflow_id=1,
        shot_ids=[1],
        image_api_key='bad-key',
    ))

    assert result['workflow_status'] == 'generating_storyboards'
    assert result['failed_shot_ids'] == [1]
```

- [ ] **Step 2: 运行测试，确认当前实现会错误继续或错误收束**

Run: `python -m pytest backend/tests/test_video_chapter_stage_api.py::test_storyboard_failure_keeps_workflow_in_storyboard_stage -q`

Expected: FAIL

- [ ] **Step 3: 最小实现失败停阶段**

```python
failed_ids: list[int] = []
for shot in target_shots:
    try:
        ...
    except Exception as exc:
        failed_ids.append(shot.id)
        update_shot(shot.id, status='failed', error_message=str(exc))

if failed_ids:
    update_workflow_status(workflow_id, 'generating_storyboards', f'{len(failed_ids)} 个镜头失败，等待人工处理')
    return {
        'workflow_status': 'generating_storyboards',
        'failed_shot_ids': failed_ids,
    }

update_workflow_status(workflow_id, 'storyboards_ready')
```

- [ ] **Step 4: 前端增加阶段继续按钮与失败筛选**

```tsx
const failedShots = workflow?.shots.filter((shot) => shot.status === 'failed') ?? [];

{failedShots.length > 0 && (
  <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
    当前阶段存在失败镜头，请先重试、跳过或修正提示词，再继续下一阶段。
  </div>
)}
```

- [ ] **Step 5: 运行后端测试和前端构建**

Run:
- `python -m pytest backend/tests/test_video_chapter_stage_api.py -q`
- `npm run build`

Expected: 两者 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/video_chapter_pipeline.py frontend/src/components/ChapterVideoWorkflowPanel.tsx backend/tests/test_video_chapter_stage_api.py
git commit -m "feat: stop workflow at failed storyboard stage"
```

## Self-Review

### Spec coverage

- 默认主模式改为分阶段手动控制 → Task 2 / Task 4 / Task 5
- 一键全自动保留 → Task 2 / Task 4
- 修复 Image2 401 鉴权 → Task 3
- 故事版失败即停 → Task 5
- 镜头级手动入口（勾选、编辑 prompt、重新分析）→ Task 4
- 保留现有模型和页面骨架 → 全计划均基于现有 `ChapterVideoWorkflow` / `ChapterVideoShot` 和现有 Layout/Panel 改造

### Placeholder scan

- 无 TBD / TODO / implement later
- 每个任务都给出了明确文件与代码骨架
- 每个任务都给出了具体测试命令与预期

### Type consistency

- 后端阶段函数命名统一：`parse_chapter_shots` / `generate_storyboards_for_shots` / `generate_videos_for_shots`
- 前端 API 命名统一：`parseChapterWorkflowShots` / `generateChapterWorkflowStoryboards` / `generateChapterWorkflowVideos`
- 工作流阶段状态统一使用：`shots_ready` / `storyboards_ready` / `videos_ready`
