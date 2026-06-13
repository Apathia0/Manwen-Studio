# Video Workflow Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让章节视频工作流取消任务级硬超时，页面关闭不影响后台继续执行，用户重开页面后自动恢复 workflow 状态与轮询。

**Architecture:** 后端通过让 `TaskManager` 支持 `timeout=None` 来移除章节视频工作流的统一任务级硬超时，同时保留 provider 级超时和失败判定。前端继续以 `ChapterVideoWorkflow` 与 `BackgroundTask` 为真源，在页面重开时自动恢复 workflow detail、assets 与 polling，而不是依赖浏览器页面常驻。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest / React 19 / TypeScript / Vitest

---

### Task 1: 为 TaskManager 的无超时任务模式补失败测试

**Files:**
- Modify: `backend/tests/test_task_manager.py`
- Test: `backend/tests/test_task_manager.py`

- [ ] **Step 1: 写失败测试，锁定 timeout=None 时不应包裹 `asyncio.wait_for`**

```python
def test_submit_task_without_timeout_does_not_use_wait_for(monkeypatch):
    from services.task_manager import TaskManager

    manager = TaskManager()
    wait_for_called = {"value": False}

    async def fake_wait_for(*args, **kwargs):
        wait_for_called["value"] = True
        return await args[0]

    async def fake_coro(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    asyncio.run(manager.submit_task("task-1", "video", fake_coro, timeout=None, max_retries=0))

    assert wait_for_called["value"] is False
```

- [ ] **Step 2: 运行测试确认先失败**

Run: `pytest backend/tests/test_task_manager.py -k without_timeout_does_not_use_wait_for -v`
Expected: FAIL，当前实现会无条件调用 `asyncio.wait_for`。

- [ ] **Step 3: 再写失败测试，锁定 timeout 有值时仍然保留 wait_for**

```python
def test_submit_task_with_timeout_still_uses_wait_for(monkeypatch):
    from services.task_manager import TaskManager

    manager = TaskManager()
    wait_for_called = {"value": False}

    async def fake_wait_for(*args, **kwargs):
        wait_for_called["value"] = True
        return await args[0]

    async def fake_coro(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    asyncio.run(manager.submit_task("task-2", "video", fake_coro, timeout=30.0, max_retries=0))

    assert wait_for_called["value"] is True
```

- [ ] **Step 4: 运行测试确认第二条能锁住兼容行为**

Run: `pytest backend/tests/test_task_manager.py -k submit_task_with_timeout_still_uses_wait_for -v`
Expected: PASS 或 FAIL 均可，但必须稳定存在，用于后续防回归。


### Task 2: 让 TaskManager 支持 timeout=None

**Files:**
- Modify: `backend/services/task_manager.py`
- Modify: `backend/tests/test_task_manager.py`
- Test: `backend/tests/test_task_manager.py`

- [ ] **Step 1: 在 `TaskManager.submit_task()` 中实现无超时分支**

```python
if timeout is None:
    return await coro_func(*args, task_id=task_id, story_id=story_id, chapter_id=chapter_id, shot_id=shot_id, **kwargs)

return await asyncio.wait_for(
    coro_func(*args, task_id=task_id, story_id=story_id, chapter_id=chapter_id, shot_id=shot_id, **kwargs),
    timeout=timeout,
)
```

- [ ] **Step 2: 保持 timeout 异常日志只在 timeout 非空路径出现**

```python
except asyncio.TimeoutError:
    logger.error(f"Task {task_id} timed out after {timeout}s")
    raise
```

- [ ] **Step 3: 运行 TaskManager 测试确认转绿**

Run: `pytest backend/tests/test_task_manager.py -k "without_timeout_does_not_use_wait_for or submit_task_with_timeout_still_uses_wait_for" -v`
Expected: PASS


### Task 3: 移除章节视频工作流的任务级硬超时

**Files:**
- Modify: `backend/services/video_chapter_pipeline.py`
- Modify: `backend/tests/test_video_chapter_workflow_api.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`

- [ ] **Step 1: 写失败测试，锁定 `start_workflow_background()` 不再传 `timeout=1800.0`**

```python
@pytest.mark.asyncio
async def test_start_workflow_background_omits_task_timeout(monkeypatch):
    captured = {}

    monkeypatch.setattr(video_chapter_pipeline, "get_workflow", lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=12, story_id=34, source_text="正文", character_reference_ids=[], video_style="写实"))

    async def fake_submit_task(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(video_chapter_pipeline.task_manager, "submit_task", fake_submit_task)

    await video_chapter_pipeline.start_workflow_background(77, api_key="video-key")

    assert captured["timeout"] is None
```

- [ ] **Step 2: 运行测试确认先失败**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k omits_task_timeout -v`
Expected: FAIL，当前实现仍传 `timeout=1800.0`。

- [ ] **Step 3: 在 `start_workflow_background()` 中将 `timeout` 改为 `None`**

```python
timeout=None,
```

- [ ] **Step 4: 运行测试确认转绿**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k omits_task_timeout -v`
Expected: PASS


### Task 4: 明确前端页面重开后的自动恢复轮询行为

**Files:**
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx`
- Modify: `frontend/src/components/videoStoryboardLayout.test.ts`
- Test: `frontend/src/components/videoStoryboardLayout.test.ts`

- [ ] **Step 1: 写失败测试，锁定 workflow 处于运行态时页面初始化会自动恢复 polling**

```typescript
it('workflow running 时页面初始化会恢复 polling', async () => {
  const latestWorkflow = { id: 10, workflow_status: 'generating_videos', chapter_id: 12 };
  // mock listChapterVideoWorkflows / getChapterVideoWorkflow / getChapterVideoWorkflowStatus
  // assert pollWorkflowUntilSettled gets scheduled
});
```

- [ ] **Step 2: 运行测试确认先失败或确认当前覆盖不足**

Run: `npm test -- src/components/videoStoryboardLayout.test.ts`
Expected: FAIL 或缺测试基座，需要补最小测试骨架。

- [ ] **Step 3: 在 `loadLatestWorkflow()` 与 `pollWorkflowUntilSettled()` 的配合上显式收敛“运行态恢复”**

```typescript
if (latest) {
  if (ACTIVE_STATUSES.has(latest.workflow_status)) {
    void pollWorkflowUntilSettled(latest.id);
  } else {
    await loadWorkflowDetail(latest.id, signal);
    setWorkflowRunning(false);
  }
}
```

- [ ] **Step 4: 确保页面卸载只 `stopPolling()`，不触发取消**

```typescript
return () => {
  aborter.abort();
  stopPolling();
};
```

- [ ] **Step 5: 运行前端测试确认通过**

Run: `npm test -- src/components/videoStoryboardLayout.test.ts`
Expected: PASS


### Task 5: 收紧运行态判断和恢复时的数据刷新顺序

**Files:**
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx`
- Test: `frontend/src/components/videoStoryboardLayout.test.ts`

- [ ] **Step 1: 写失败测试，锁定恢复时会同时刷新 workflow detail 和 chapter assets**

```typescript
it('恢复运行态时刷新 workflow detail 与 chapter assets', async () => {
  // mock loadChapterAssets + getChapterVideoWorkflow
  // assert both are called during recovery
});
```

- [ ] **Step 2: 运行测试确认先失败或未覆盖**

Run: `npm test -- src/components/videoStoryboardLayout.test.ts`
Expected: FAIL 或需新增断言。

- [ ] **Step 3: 在 polling settled 和 latest workflow 恢复路径上统一刷新顺序**

```typescript
const detail = await getChapterVideoWorkflow(workflowId)
setWorkflow(detail)
await loadChapterAssets(status.chapter_id)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- src/components/videoStoryboardLayout.test.ts`
Expected: PASS


### Task 6: 最终验证与文档注记

**Files:**
- Modify: `docs/superpowers/specs/2026-06-12-video-workflow-resume-design.md`
- Test: `backend/tests/test_task_manager.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`
- Test: `frontend/src/components/videoStoryboardLayout.test.ts`

- [ ] **Step 1: 运行后端关键测试集合**

Run: `pytest backend/tests/test_task_manager.py backend/tests/test_video_chapter_workflow_api.py -k "timeout or workflow" -v`
Expected: PASS

- [ ] **Step 2: 运行前端恢复轮询测试**

Run: `npm test -- src/components/videoStoryboardLayout.test.ts`
Expected: PASS

- [ ] **Step 3: 补实现注记到状态恢复 spec 文档**

```markdown
## Implementation Notes

- chapter video workflow 已取消任务级硬超时
- timeout=None 模式已在 TaskManager 中支持
- 页面重开后会自动恢复 workflow 状态与轮询
```

- [ ] **Step 4: 做一次手动冒烟验证**

Run:
- `启动一个长视频任务`
- `关闭页面`
- `等待后台继续执行`
- `重新打开页面`

Expected:
- 任务未因页面关闭而失败
- 页面自动恢复运行态与轮询
- 最终可看到完成或失败结果
