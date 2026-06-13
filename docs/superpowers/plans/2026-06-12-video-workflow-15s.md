# Video Workflow 15s Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前视频工作流从固定 10 秒一镜升级为固定 15 秒一镜，并让 AI 先进行 15 秒镜头容量建模，再输出 storyboard 与 video 共用的一份分镜脚本结构。

**Architecture:** 先统一后端的 shot 时长常量与标准化规则，再重写提示词模板，让 AI 在 15 秒约束下动态决定镜头内分镜段落数量与内容。最后收口 chapter workflow 的旧模板检测和章节级 storyboard 生成逻辑，确保 storyboard prompt 与 video prompt 共享同一份 15 秒分镜脚本。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest / React 19 / TypeScript / Vitest

---

### Task 1: 固化 15 秒 shot 时长的基础测试

**Files:**
- Modify: `backend/tests/test_video_chapter_workflow_api.py`
- Modify: `backend/tests/test_video_chapter_stage_api.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 为章节级 storyboard 标准化补失败测试，锁定 shot 时长必须为 15 秒**

```python
def test_normalize_chapter_shot_uses_15_seconds_default():
    from routers import video as video_router

    result = video_router._normalize_chapter_shot({}, 1, 15)

    assert result["duration_seconds"] == 15
```

- [ ] **Step 2: 运行单测确认先失败**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k normalize_chapter_shot_uses_15_seconds_default -v`
Expected: FAIL，当前实现仍会把 duration clamp 到 10。

- [ ] **Step 3: 为 workflow 视频轮询与默认时长补失败测试**

```python
def test_poll_video_job_preserves_15s_result(monkeypatch):
    from services import video_chapter_pipeline

    async def fake_query_job_status(**kwargs):
        return {"status": "succeeded"}

    async def fake_fetch_job_result(**kwargs):
        return {"video_path": "/static/video/test.mp4", "duration_seconds": 15}

    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, "query_job_status", fake_query_job_status)
    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, "fetch_job_result", fake_fetch_job_result)

    result = asyncio.run(video_chapter_pipeline._poll_video_job(
        provider="test", provider_job_id="job-1", api_key="k"
    ))

    assert result == "/static/video/test.mp4"
```

- [ ] **Step 4: 运行测试确认先失败或至少锁住当前行为**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k poll_video_job_preserves_15s_result -v`
Expected: PASS 或 FAIL 都可以，但用例必须稳定存在，用于后续防回归。


### Task 2: 统一后端 shot 默认时长、clamp 与 fallback

**Files:**
- Modify: `backend/routers/video.py`
- Modify: `backend/tests/test_video_chapter_workflow_api.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`

- [ ] **Step 1: 写失败测试，覆盖 fallback storyboard 默认时长为 15 秒**

```python
def test_fallback_chapter_storyboard_uses_15_seconds():
    from routers import video as video_router

    shots = video_router._fallback_chapter_storyboard("她停下脚步。\n她抬头。", 2)

    assert shots
    assert all(shot["duration_seconds"] == 15 for shot in shots)
```

- [ ] **Step 2: 运行测试确认先失败**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k fallback_chapter_storyboard_uses_15_seconds -v`
Expected: FAIL，当前 fallback 硬编码 10 秒。

- [ ] **Step 3: 在 `backend/routers/video.py` 引入统一常量并改最小实现**

```python
SHOT_DURATION_SECONDS = 15

default_dur = min(SHOT_DURATION_SECONDS, max(5, 135 // max(1, len(raw_shots))))

"duration_seconds": min(SHOT_DURATION_SECONDS, int(raw.get("duration_seconds") or default_duration))

"duration_seconds": SHOT_DURATION_SECONDS
```

- [ ] **Step 4: 将手动创建 shot、视频 render 请求、redo job 时长 clamp 全部统一改为 15**

```python
duration = max(1, min(SHOT_DURATION_SECONDS, body.duration_seconds or shot.duration_seconds or SHOT_DURATION_SECONDS))
```

- [ ] **Step 5: 运行测试确认转绿**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k "normalize_chapter_shot_uses_15_seconds_default or fallback_chapter_storyboard_uses_15_seconds" -v`
Expected: PASS


### Task 3: 重写 15 秒镜头容量建模的提示词模板

**Files:**
- Modify: `backend/services/video_chapter_prompts.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`

- [ ] **Step 1: 写失败测试，锁定提示词中不再出现旧 10 秒时间轴文本**

```python
def test_shot_video_prompt_template_no_longer_uses_10s_segments():
    from services import video_chapter_prompts as prompts

    assert "7-10秒" not in prompts.SHOT_VIDEO_SYSTEM_PROMPT
    assert "8.5-10秒" not in prompts.SHOT_VIDEO_SYSTEM_PROMPT
```

- [ ] **Step 2: 运行测试确认先失败**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k shot_video_prompt_template_no_longer_uses_10s_segments -v`
Expected: FAIL，当前模板仍包含 10 秒分段文本。

- [ ] **Step 3: 将模板目标从“固定10秒镜头”改成“15秒镜头容量建模”**

```python
"你是一位经验丰富的视频导演，需要先判断这个镜头在 15 秒内能承载多少内容，再决定如何拆成若干分镜段落。"
```

- [ ] **Step 4: 删除固定 3 段 / 6 段硬编码，改为要求 AI 动态输出分镜脚本段落**

```python
"请先输出 15 秒镜头内的分镜脚本段落列表，每段包含：起止时间、画面任务、角色动作、运镜、节奏功能。段落数量由导演判断，不预设固定值。"
"然后基于这同一份分镜脚本，同时生成 storyboard_prompt 与 video_prompt，两者不得自行改写段落结构。"
```

- [ ] **Step 5: 运行测试确认转绿**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k shot_video_prompt_template_no_longer_uses_10s_segments -v`
Expected: PASS


### Task 4: 让 storyboard prompt 与 video prompt 共享同一份动态分镜脚本结构

**Files:**
- Modify: `backend/services/video_chapter_prompts.py`
- Modify: `backend/services/deepseek.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`

- [ ] **Step 1: 写失败测试，锁定 AI 生成结果必须共享同一组结构化段落字段，并允许动态段数**

```python
def test_storyboard_and_video_prompts_share_same_segment_schema():
    from services import video_chapter_prompts as prompts

    assert "segments" in prompts.SHOT_VIDEO_SYSTEM_PROMPT
    assert "storyboard_prompt" in prompts.SHOT_VIDEO_SYSTEM_PROMPT
    assert "video_prompt" in prompts.SHOT_VIDEO_SYSTEM_PROMPT
    assert "段落数量由导演判断" in prompts.SHOT_VIDEO_SYSTEM_PROMPT
```

- [ ] **Step 2: 运行测试确认先失败或确认当前未覆盖此语义**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k storyboard_and_video_prompts_share_same_segment_schema -v`
Expected: FAIL 或缺失字段，表明需要新增结构约束。

- [ ] **Step 3: 在提示词模板中明确要求输出统一的 `segments` 结构，并强调段数动态决定**

```python
{
  "segments": [
    {
      "start_second": 0.0,
      "end_second": 4.2,
      "story_task": "...",
      "visual_action": "...",
      "camera_direction": "...",
      "rhythm_function": "..."
    }
  ],
  "storyboard_prompt": "...",
  "video_prompt": "..."
}

# 注意：segments 的数量不是固定值，AI 需要根据 15 秒内容密度、动作复杂度和剧情推进动态决定。
```

- [ ] **Step 4: 更新 DeepSeek 解析逻辑，确保后续 regenerate/复用时读取新的 `segments` 结构，并保留动态段数**

```python
segments = payload.get("segments") or []
```

- [ ] **Step 5: 运行测试确认转绿**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k storyboard_and_video_prompts_share_same_segment_schema -v`
Expected: PASS


### Task 5: 更新 chapter workflow regenerate 与旧模板检测逻辑

**Files:**
- Modify: `backend/services/video_chapter_pipeline.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 写失败测试，锁定旧 10 秒模板检测不再依赖固定 `0-3 秒` 结构**

```python
def test_video_prompt_stale_detection_identifies_legacy_10s_pattern():
    stale_prompt = "0-3 秒：她回头。3-7 秒：她停顿。7-10 秒：她离开。"
    assert "7-10 秒" in stale_prompt
```

- [ ] **Step 2: 运行测试确认当前实现依赖旧 10 秒标记**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k stale_detection -v`
Expected: FAIL 或需新增测试以证明当前逻辑依赖旧标记。

- [ ] **Step 3: 将 `is_stale_template` 判定切换到新的 15 秒分镜脚本结构特征**

```python
is_stale_template = bool(video_prompt) and (
    "7-10 秒" in video_prompt
    or "8.5-10 秒" in video_prompt
    or "0-3 秒" in video_prompt
)
```

改为围绕新 `segments` 结构存在性与旧 10 秒残留文本的综合判断。

- [ ] **Step 4: 将 workflow 默认提交的 `duration_seconds=10` 改为 15**

```python
duration_seconds=15
```

- [ ] **Step 5: 运行相关测试确认通过**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k "video or storyboard" -v`
Expected: PASS 或仅保留与本任务无关的既有失败。


### Task 6: 更新章节级 storyboard 生成提示与默认时长

**Files:**
- Modify: `backend/routers/video.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`

- [ ] **Step 1: 写失败测试，锁定章节级 storyboard prompt 文案已切到 15 秒**

```python
def test_chapter_storyboard_prompt_mentions_15_second_shots():
    prompt = build_prompt_somehow()
    assert "15s" in prompt or "15 秒" in prompt
```

- [ ] **Step 2: 运行测试确认先失败**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k chapter_storyboard_prompt_mentions_15_second_shots -v`
Expected: FAIL，当前文案仍写 10s per shot。

- [ ] **Step 3: 修改章节级 storyboard AI 指导文案与默认时长计算**

```python
"Duration: default 15s per shot. The AI director must decide how many internal storyboard beats fit inside this 15-second shot, based on content density and cinematic pacing."
default_dur = min(SHOT_DURATION_SECONDS, max(8, 135 // max(1, len(raw_shots))))
```

- [ ] **Step 4: 运行测试确认转绿**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py -k chapter_storyboard_prompt_mentions_15_second_shots -v`
Expected: PASS


### Task 7: 同步前端说明文案与最终验证

**Files:**
- Modify: `frontend/src/prompts/video-storyboard.ts`
- Modify: `docs/superpowers/specs/2026-06-12-video-workflow-15s-design.md`
- Test: `backend/tests/test_video_chapter_workflow_api.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 检查并更新前端仍可触达的 10 秒提示词示例文案**

```typescript
"固定 15 秒镜头，先做容量建模，再输出分镜脚本。"
```

- [ ] **Step 2: 运行后端关键测试集合**

Run: `pytest backend/tests/test_video_chapter_workflow_api.py backend/tests/test_video_chapter_stage_api.py -v`
Expected: 15 秒相关新增用例全部通过。

- [ ] **Step 3: 补实现注记到 spec 文档末尾**

```markdown
## Implementation Notes

- shot 默认时长已统一为 15 秒
- storyboard / video prompt 已切换到共享分镜脚本结构
- 旧 10 秒模板检测已移除或替换
```

- [ ] **Step 4: 做一次手动冒烟验证**

Run:
- `从正文拆镜`
- `生成 storyboard prompt`
- `生成 video prompt`
- `提交视频生成`

Expected:
- shot 时长均为 15
- AI 能合理判断 15 秒内容密度
- storyboard 与 video prompt 使用同一份分镜脚本
- 分镜段落数量由 AI 动态决定，而不是固定模板
