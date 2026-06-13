# 视频工作台异步化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将视频工作台中长耗时的操作（故事版生成、视频生成、重新分析提示词、生成镜头详情）改为后台异步执行。用户关闭窗口后任务继续执行，再次打开能看到进度，完成后自动渲染。

**Architecture:** 后端利用已有的 `task_manager.submit_task()` 将 4 个长耗时端点改为提交后台任务后立即返回；前端对应的 handler 改为不 await HTTP 响应，提交后立即启动已有轮询机制（`pollWorkflowUntilSettled`）。利用已有的 `workflow_status` 字段做状态跟踪——无需新增轮询端点。

**Tech Stack:** Python 3.11 / FastAPI / TypeScript / React 19

---

### Task 1: Pipeline — 为 reanalyze 和 generate-details 添加 workflow_status 跟踪

**Files:**
- Modify: `backend/services/video_chapter_pipeline.py`

当前 `generate_shot_details_batch` 和 `reanalyze_storyboard_prompts` 不设置工作流状态。需要让它们更新 `workflow_status`，这样前端通过 `ACTIVE_STATUSES` 判断能检测到运行中并持续轮询。

- [ ] **Step 1: 给 `generate_shot_details_batch` 添加状态更新**

在函数开头（`logger.info` 之后）添加：
```python
update_workflow_status(workflow_id, "generating_details")
```

在函数末尾添加（`return {"success": True, ...}` 之前）：
```python
update_workflow_status(workflow_id, "shots_ready")
```

这两个调用在已有函数内即可。需要确认函数内已有 `from ... import update_workflow_status`——如果还没有就需要添加 import。

- [ ] **Step 2: 给 `reanalyze_storyboard_prompts` 添加状态更新**

在函数开头（`logger.info` 之后）添加状态保存和更新：
```python
# 保存当前状态待后续恢复
_prev_status = get_workflow(workflow_id).workflow_status if get_workflow(workflow_id) else "shots_ready"
update_workflow_status(workflow_id, "reanalyzing_prompts")
```

在函数末尾（`return` 之前）恢复状态：
```python
update_workflow_status(workflow_id, _prev_status)
```

如果遇到异常，在 `except` 中也恢复状态。

需要导入 `get_workflow`（检查是否已在文件顶部导入）。

- [ ] **Step 3: 验证 Python 语法**

```bash
cd backend
python -m py_compile services/video_chapter_pipeline.py
```

Expected: 无错误输出。

---

### Task 2: Backend — 将 `/storyboards` 和 `/videos` 端点改为后台任务

**Files:**
- Modify: `backend/routers/video.py`

当前 `api_generate_storyboards` 和 `api_generate_videos` 直接 `await`  pipeline 函数，HTTP 连接保持 30s~30min。改为通过 `task_manager.submit_task()` 提交后台任务后立即返回。

- [ ] **Step 1: 修改 `api_generate_storyboards`**

**当前代码**（约 6794-6841 行）:
```python
@router.post("/api/video/chapter-workflows/{workflow_id}/storyboards")
async def api_generate_storyboards(...):
    # ... 参数验证和准备（保留）
    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"
    # ... ref_ids 刷新（保留）
    result = await generate_storyboards_for_shots(
        workflow_id=workflow_id,
        story_id=wf.story_id,
        shot_ids=body.shot_ids or None,
        image_api_key=image_api_key,
        deepseek_api_key=deepseek_api_key,
        character_reference_ids=ref_ids,
        task_id=task_id,
    )
    return result
```

**改为**：
```python
@router.post("/api/video/chapter-workflows/{workflow_id}/storyboards")
async def api_generate_storyboards(...):
    # ... 参数验证和准备（保留）
    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"
    # ... ref_ids 刷新（保留）

    # 先设置工作流状态，确保前端轮询能立即检测到
    update_workflow_status(workflow_id, "generating_storyboards")

    # 提交后台任务
    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_storyboards",
            coro_func=generate_storyboards_for_shots,
            workflow_id=workflow_id,
            story_id=wf.story_id,
            shot_ids=body.shot_ids or None,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            character_reference_ids=ref_ids,
            timeout=600.0,
            max_retries=1,
        )
    except Exception as exc:
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "generating_storyboards",
        "message": "故事版生成任务已提交后台执行",
    }
```

- [ ] **Step 2: 修改 `api_generate_videos`**

**改为**（类似模式）：
```python
@router.post("/api/video/chapter-workflows/{workflow_id}/videos")
async def api_generate_videos(...):
    # ... 参数验证和准备（保留）
    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"
    # ... ref_ids 刷新（保留）

    # 先设置工作流状态
    update_workflow_status(workflow_id, "generating_videos")

    # 提交后台任务
    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_videos",
            coro_func=generate_videos_for_shots,
            workflow_id=workflow_id,
            shot_ids=body.shot_ids or None,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            video_api_key=video_api_key,
            video_base_url=video_base_url,
            video_model=video_model,
            timeout=1800.0,
            max_retries=1,
        )
    except Exception as exc:
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "generating_videos",
        "message": "视频生成任务已提交后台执行",
    }
```

- [ ] **Step 3: 验证 Python 语法**

```bash
cd backend
python -m py_compile routers/video.py
```

Expected: 无错误输出。

---

### Task 3: Backend — 将 `/generate-details` 和 `/reanalyze-prompt` 端点改为后台任务

**Files:**
- Modify: `backend/routers/video.py`

- [ ] **Step 1: 修改 `api_generate_shot_details`**

**改为**：
```python
@router.post("/api/video/chapter-workflows/{workflow_id}/generate-details")
async def api_generate_shot_details(...):
    # ... 参数验证和准备（保留）

    task_id = f"chapter_video_{workflow_id}_detail_{uuid.uuid4().hex[:8]}"

    update_workflow_status(workflow_id, "generating_details")

    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_generate_details",
            coro_func=generate_shot_details_batch,
            workflow_id=workflow_id,
            shot_ids=body.shot_ids,
            chapter_text=wf.source_text or "",
            story_id=wf.story_id,
            deepseek_api_key=deepseek_api_key,
            timeout=120.0,
            max_retries=1,
        )
    except Exception as exc:
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "generating_details",
        "message": "镜头详情生成任务已提交后台执行",
    }
```

- [ ] **Step 2: 修改 `api_reanalyze_storyboard_prompts`**

**改为**：
```python
@router.post("/api/video/chapter-workflows/{workflow_id}/storyboards/reanalyze-prompt")
async def api_reanalyze_storyboard_prompts(...):
    # ... 参数验证和准备（保留）

    shot_ids = body.get("shot_ids")
    if not shot_ids:
        raise HTTPException(400, "请指定至少一个镜头")

    task_id = f"chapter_video_{workflow_id}_reanalyze_{uuid.uuid4().hex[:8]}"

    # 保存当前状态 + 设置 reanalyzing 状态
    from services.video_chapter_pipeline import get_workflow
    wf_for_status = get_workflow(workflow_id)
    _prev_status = wf_for_status.workflow_status if wf_for_status else "shots_ready"
    update_workflow_status(workflow_id, "reanalyzing_prompts")

    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_reanalyze",
            coro_func=reanalyze_storyboard_prompts,
            workflow_id=workflow_id,
            shot_ids=shot_ids,
            deepseek_api_key=deepseek_api_key,
            timeout=300.0,
            max_retries=1,
        )
    except Exception as exc:
        # 提交失败时恢复状态
        update_workflow_status(workflow_id, _prev_status)
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "reanalyzing_prompts",
        "message": "提示词重新分析任务已提交后台执行",
    }
```

- [ ] **Step 3: `reanalyze_storyboard_prompts` 恢复旧状态**

函数内需要保存并恢复旧状态。在 Task 1 的 Step 2 中已添加了 `_prev_status` 保存和恢复。需要在异常处理中也恢复状态。修改函数中的异常处理部分：

在 `reanalyze_storyboard_prompts` 的循环中，当前 `try/except` 是：
```python
for shot in target_shots:
    try:
        # ... processing
    except Exception as e:
        logger.warning(...)
```

在 `except` 块中**不**需要回退状态（其他镜头继续）。但如果在循环之前或之后有全局异常，在调用方 `_on_task_complete` 中会自动标记为 failed。不过更精细的做法是在函数最外层用 try/finally 恢复状态：

```python
_prev_status = get_workflow(workflow_id).workflow_status if get_workflow(workflow_id) else "shots_ready"
try:
    update_workflow_status(workflow_id, "reanalyzing_prompts")
    # ... existing processing ...
except Exception:
    update_workflow_status(workflow_id, _prev_status)
    raise
else:
    update_workflow_status(workflow_id, _prev_status)
```

- [ ] **Step 4: 验证 Python 语法**

```bash
cd backend
python -m py_compile routers/video.py
python -m py_compile services/video_chapter_pipeline.py
```

Expected: 无错误输出。

---

### Task 4: Frontend — 修改 handler + 更新轮询状态

**Files:**
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx`

- [ ] **Step 1: 将 `reanalyzing_prompts` 和 `generating_details` 加入 ACTIVE_STATUSES**

```typescript
// 第 120 行附近
const ACTIVE_STATUSES = new Set([
  'parsing_shots',
  'generating_storyboards',
  'generating_videos',
  'reanalyzing_prompts',
  'generating_details',
]);
```

- [ ] **Step 2: 修改 `handleGenerateStoryboards` — 不再 await 响应**

**当前代码**（约 396-411 行）:
```typescript
const handleGenerateStoryboards = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) {
      toast.error('请先勾选需要生成故事版的镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      await generateChapterWorkflowStoryboards(workflow.id, { shot_ids: shotIds });
      toast.success('故事版生成任务已启动');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`故事版生成失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);
```

**改为**：
```typescript
const handleGenerateStoryboards = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) {
      toast.error('请先勾选需要生成故事版的镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      // 不再 await 响应 — 任务提交后由轮询跟踪进度
      generateChapterWorkflowStoryboards(workflow.id, { shot_ids: shotIds }).catch((error: any) => {
        console.error('故事版生成任务提交失败', error);
      });
      toast.success('故事版生成任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`故事版生成失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);
```

- [ ] **Step 3: 修改 `handleGenerateVideos` — 不再 await 响应**

**改为**（同样模式）:
```typescript
const handleGenerateVideos = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) {
      toast.error('请先勾选需要生成视频的镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      generateChapterWorkflowVideos(workflow.id, { shot_ids: shotIds }).catch((error: any) => {
        console.error('视频生成任务提交失败', error);
      });
      toast.success('视频生成任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`视频生成失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);
```

- [ ] **Step 4: 修改 `handleReanalyzePrompt` — 改为批量 API + 不 await**

**当前代码**（约 481-496 行）:
```typescript
const handleReanalyzePrompt = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) return;
    try {
      setWorkflowRunning(true);
      for (const shotId of shotIds) {
        await reanalyzeChapterShotPrompts(shotId);
      }
      toast.success(`提示词已重新分析（${shotIds.length} 个镜头）`);
      await handleRefreshWorkflow();
    } catch (error: any) {
      toast.error(`重新分析失败: ${error.message || '未知错误'}`);
    } finally {
      setWorkflowRunning(false);
    }
  }, [workflow, handleRefreshWorkflow]);
```

**改为**（使用已存在的 `reanalyzeChapterWorkflowStoryboardPrompt` 批量端点）：
```typescript
const handleReanalyzePrompt = useCallback(async (shotIds: number[]) => {
    if (!workflow) return;
    if (shotIds.length === 0) return;
    try {
      setWorkflowRunning(true);
      reanalyzeChapterWorkflowStoryboardPrompt(workflow.id, { shot_ids: shotIds }).catch((error: any) => {
        console.error('提示词重分析任务提交失败', error);
      });
      toast.success('提示词重新分析任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`重新分析失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);
```

确保顶部 import 中添加 `reanalyzeChapterWorkflowStoryboardPrompt`（检查是否已导入，当前第 33 行的 `reanalyzeChapterShotPrompts` 旁边可能有）。

- [ ] **Step 5: 修改 `handleGenerateShotDetails` — 不 await 响应**

**当前代码**（约 256-277 行）:
```typescript
const handleGenerateShotDetails = useCallback(async (shotIds: number[]) => {
    if (!workflow || shotIds.length === 0) return;
    if (shotIds.length > 5) {
      toast.error('最多支持 5 个镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      const result = await generateChapterWorkflowShotDetails(workflow.id, { shot_ids: shotIds });
      if (result.success) {
        toast.success(`已为 ${result.total} 个镜头生成详情`);
      } else {
        toast.error(result.error || '生成详情失败');
      }
      const detail = await getChapterVideoWorkflow(workflow.id);
      setWorkflow(detail);
    } catch (error: any) {
      toast.error(`生成详情失败: ${error.message || '未知错误'}`);
    } finally {
      setWorkflowRunning(false);
    }
  }, [workflow]);
```

**改为**：
```typescript
const handleGenerateShotDetails = useCallback(async (shotIds: number[]) => {
    if (!workflow || shotIds.length === 0) return;
    if (shotIds.length > 5) {
      toast.error('最多支持 5 个镜头');
      return;
    }
    try {
      setWorkflowRunning(true);
      generateChapterWorkflowShotDetails(workflow.id, { shot_ids: shotIds }).catch((error: any) => {
        console.error('镜头详情生成任务提交失败', error);
      });
      toast.success('镜头详情生成任务已提交');
      void pollWorkflowUntilSettled(workflow.id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`生成详情失败: ${error.message || '未知错误'}`);
    }
  }, [pollWorkflowUntilSettled, workflow]);
```

- [ ] **Step 6: 验证前端构建**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 无 TypeScript 错误。

---

### Task 5: 验证

- [ ] **Step 1: 后端 Python 语法检查**

```bash
cd backend
python -m py_compile routers/video.py
python -m py_compile services/video_chapter_pipeline.py
```

Expected: 无错误输出。

- [ ] **Step 2: 运行 pytest**

```bash
cd backend
pytest tests/ -x -v 2>&1 | tail -30
```

Expected: 所有已存在测试通过。无法通过的请确认是 pre-existing 错误而非本计划引入。

- [ ] **Step 3: 前端 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 无 TypeScript 错误。

- [ ] **Step 4: 前端构建**

```bash
cd frontend
npm run build
```

Expected: 构建成功，无错误。
