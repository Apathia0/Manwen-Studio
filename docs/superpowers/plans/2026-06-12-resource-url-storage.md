 # Resource URL Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 StoryCanvas 中图片资源和视频资源的落库与回显规则：有 OSS URL 就存 OSS URL，无 OSS 才存本地相对路径，同时前端兼容完整 URL 与本地相对路径。

**Architecture:** 后端在各资源生成/上传/重绘入口统一接收服务返回值并决定最终写库内容，禁止无条件回写 `output_path`。前端所有资源 URL helper 统一先识别完整 `http(s)` URL，再回退到现有 `/static/...` 拼接规则；对依赖本地文件的二次编辑入口按点补兼容，而不是引入新的全局资源层。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest / React 19 / TypeScript / Vitest

---

### Task 1: 盘点后端资源写库入口并固化失败测试

**Files:**
- Modify: `backend/tests/test_story_cover_api.py`
- Create: `backend/tests/test_resource_url_storage_plan_inventory.md`
- Test: `backend/tests/test_story_cover_api.py`

- [ ] **Step 1: 扩展后端失败测试清单，先覆盖“写库优先使用服务返回值”规则**

```python
def test_generate_story_cover_persists_oss_url(monkeypatch):
    ...


def test_generate_story_cover_falls_back_to_relative_path(monkeypatch):
    db = _Db()
    user = SimpleNamespace(id=1)
    story = SimpleNamespace(id=114, cover_image=None)
    output_path = Path("manga_outputs/covers/cover_114_test.png")
    request = _Request({"instruction": "生成封面"})

    monkeypatch.setattr(main, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main, "_require_story_for_user", lambda story_id, current_user, db: story)
    monkeypatch.setattr(main, "_build_story_cover_prompt", lambda story, instruction: "prompt")
    monkeypatch.setattr(main, "_story_cover_output_path", lambda story_id: output_path)
    monkeypatch.setattr(main, "_user_image_api_key", lambda request: "img-key")
    monkeypatch.setattr(main, "_check_and_consume_feature_quota", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_release_db_transaction", lambda db: None)
    monkeypatch.setattr(main, "generate_cover_image", lambda *args, **kwargs: str(output_path))

    result = _run(main.generate_story_cover(114, request, db))

    assert story.cover_image == "manga_outputs/covers/cover_114_test.png"
    assert result["cover_image"] == "manga_outputs/covers/cover_114_test.png"
```

- [ ] **Step 2: 运行后端测试，确认新增用例先失败**

Run: `pytest backend/tests/test_story_cover_api.py -v`
Expected: 新增回退用例可能通过，但若实现仍不完整，至少存在一条围绕落库策略的失败用例；不得是语法错误。

- [ ] **Step 3: 写盘点说明文件，列出后端所有候选资源入口**

```markdown
# 后端资源写库入口盘点

- `backend/main.py`
  - `generate_story_cover`
  - `adjust_story_cover`
  - 漫画生成相关入口
- `backend/routers/video.py`
  - 故事版上传/替换
  - 视频上传/替换
- `backend/services/video_chapter_pipeline.py`
  - 资产生成后的模型字段更新
- `backend/services/video_api.py`
  - 视频文件生成后的返回值
```
```

- [ ] **Step 4: 复跑后端测试，确认盘点文件不影响测试状态**

Run: `pytest backend/tests/test_story_cover_api.py -v`
Expected: 与上一步相同的失败集合，不新增无关错误。


### Task 2: 统一后端图片资源落库辅助逻辑

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_story_cover_api.py`
- Test: `backend/tests/test_story_cover_api.py`

- [ ] **Step 1: 写失败测试，覆盖“完整 URL 直存、相对路径回退”的共用辅助逻辑**

```python
def test_store_story_cover_result_keeps_full_url():
    story = SimpleNamespace(cover_image=None)

    result = main._store_story_cover_result(
        story,
        Path("manga_outputs/covers/test.png"),
        "https://oss.aifusion6.cn/manga_outputs/covers/test.png",
    )

    assert result == "https://oss.aifusion6.cn/manga_outputs/covers/test.png"
    assert story.cover_image == "https://oss.aifusion6.cn/manga_outputs/covers/test.png"
```

- [ ] **Step 2: 运行单测确认新增辅助逻辑测试先失败**

Run: `pytest backend/tests/test_story_cover_api.py::test_store_story_cover_result_keeps_full_url -v`
Expected: FAIL，若函数不存在则报 attribute error；不得是导入错误。

- [ ] **Step 3: 在 `backend/main.py` 写最小实现**

```python
def _store_story_cover_result(story: Story, generated_path: Path, stored_path: str) -> str:
    normalized = str(stored_path or "").strip()
    if normalized.startswith(("http://", "https://")):
        story.cover_image = normalized
        return normalized
    return _replace_story_cover_from_path(story, generated_path)
```

- [ ] **Step 4: 让封面生成与封面调整统一使用该辅助逻辑**

```python
generated_cover_path = await generate_cover_image(...)
...
_store_story_cover_result(story, output_path, generated_cover_path)

generated_cover_path = await edit_existing_image(...)
...
_store_story_cover_result(story, output_path, generated_cover_path)
```

- [ ] **Step 5: 运行后端测试确认转绿**

Run: `pytest backend/tests/test_story_cover_api.py -v`
Expected: PASS，封面 URL 写库规则用例全部通过。


### Task 3: 统一后端图片类其他入口的最终写库规则

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/routers/video.py`
- Modify: `backend/services/video_chapter_pipeline.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 在相关测试文件中补失败用例，覆盖故事版/资产图结果为完整 URL 时的持久化行为**

```python
@pytest.mark.asyncio
async def test_storyboard_generation_keeps_http_image_path(monkeypatch):
    async def fake_generate_manga_image(**kwargs):
        return SimpleNamespace(image_path="https://oss.aifusion6.cn/manga_outputs/storyboard.png")

    monkeypatch.setattr(image_service, "generate_manga_image", fake_generate_manga_image)
    ...
    assert saved_shot.storyboard_image_path == "https://oss.aifusion6.cn/manga_outputs/storyboard.png"
```

- [ ] **Step 2: 运行相关测试确认先失败**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k storyboard -v`
Expected: 至少新增一条失败，表明当前仍在错误改写或丢弃完整 URL。

- [ ] **Step 3: 在图片类入口中统一遵守“优先服务返回值”规则**

```python
result = await image_service.generate_manga_image(...)
image_path = str(result.image_path or "").strip()
if image_path.startswith(("http://", "https://")):
    shot.storyboard_image_path = image_path
else:
    shot.storyboard_image_path = f"manga_outputs/{relative_name}"
```

- [ ] **Step 4: 运行测试确认图片类入口转绿**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k storyboard -v`
Expected: PASS，故事版/资产图相关 URL 持久化测试通过。


### Task 4: 统一后端视频类入口的最终写库规则

**Files:**
- Modify: `backend/routers/video.py`
- Modify: `backend/services/video_api.py`
- Modify: `backend/services/video_chapter_pipeline.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`

- [ ] **Step 1: 补失败测试，覆盖视频生成结果返回完整 URL 时的持久化行为**

```python
@pytest.mark.asyncio
async def test_video_generation_keeps_http_video_path(monkeypatch):
    async def fake_poll_video_job(*args, **kwargs):
        return "https://oss.aifusion6.cn/video_outputs/test.mp4"

    monkeypatch.setattr(video_gen_service, "poll_video_job", fake_poll_video_job)
    ...
    assert saved_shot.video_path == "https://oss.aifusion6.cn/video_outputs/test.mp4"
```

- [ ] **Step 2: 运行视频测试确认先失败**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k video -v`
Expected: FAIL，体现当前视频结果仍存在相对路径强制回写或展示不一致问题。

- [ ] **Step 3: 在视频类保存点统一接收最终返回值**

```python
video_result = await regenerate_shot_video(...)
final_video_path = str(video_result or "").strip()
if final_video_path.startswith(("http://", "https://")):
    shot.video_path = final_video_path
else:
    shot.video_path = f"video_outputs/{filename}"
```

- [ ] **Step 4: 运行视频测试确认转绿**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k video -v`
Expected: PASS，视频 URL 持久化相关用例通过。


### Task 5: 前端统一资源 URL helper

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Test: `frontend/src/api.test.ts`

- [ ] **Step 1: 补失败测试，覆盖视频与图片 helper 的完整 URL 直返行为**

```typescript
it('保留完整 OSS URL', () => {
  const ossUrl = 'https://oss.aifusion6.cn/manga_outputs/covers/cover_114_test.png';
  expect(coverImageUrl(ossUrl)).toBe(ossUrl);
});

it('保留完整视频 URL', () => {
  const videoUrl = 'https://oss.aifusion6.cn/video_outputs/test.mp4';
  expect(toPublicAssetUrl(videoUrl, 'video')).toBe(videoUrl);
});
```

- [ ] **Step 2: 运行前端测试确认先失败**

Run: `npm test -- src/api.test.ts`
Expected: FAIL，至少一条完整 URL 直返用例失败。

- [ ] **Step 3: 在 `frontend/src/api.ts` 中统一 helper 规则**

```typescript
function isAbsoluteAssetUrl(value: string): boolean {
  return /^https?:\/\//.test(value);
}

export function coverImageUrl(coverPath: string | null | undefined): string | null {
  if (!coverPath) return null;
  if (isAbsoluteAssetUrl(coverPath)) return coverPath;
  return `${BASE}/static/manga/${coverPath.replace('manga_outputs/', '')}`;
}
```

- [ ] **Step 4: 将其他图片/视频 URL helper 收敛到同一判定函数**

```typescript
export function toPublicVideoUrl(videoPath: string | null | undefined): string | null {
  if (!videoPath) return null;
  if (isAbsoluteAssetUrl(videoPath)) return videoPath;
  return `${BASE}/static/video/${videoPath.replace('video_outputs/', '')}`;
}
```

- [ ] **Step 5: 运行前端测试确认转绿**

Run: `npm test -- src/api.test.ts`
Expected: PASS，完整 URL 与相对路径两类输入都通过。


### Task 6: 修复依赖本地文件的二次编辑入口兼容性

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/services/image2.py`
- Modify: `backend/routers/video.py`
- Test: `backend/tests/test_story_cover_api.py`

- [ ] **Step 1: 为一个代表性的二次编辑入口补失败测试，覆盖“数据库存 OSS URL 时仍可进入编辑”**

```python
def test_adjust_story_cover_accepts_remote_cover_url(monkeypatch, tmp_path):
    story = SimpleNamespace(id=114, cover_image="https://oss.aifusion6.cn/manga_outputs/covers/test.png")
    ...
    monkeypatch.setattr(main, "_materialize_remote_asset", lambda url: tmp_path / "downloaded.png")
    result = _run(main.adjust_story_cover(114, request, db))
    assert result["cover_image"].startswith("https://")
```

- [ ] **Step 2: 运行测试确认先失败**

Run: `pytest backend/tests/test_story_cover_api.py -k remote_cover -v`
Expected: FAIL，当前逻辑若直接 `Path(...)/story.cover_image` 会无法处理远程 URL。

- [ ] **Step 3: 为确实依赖本地文件的入口补轻量兼容逻辑**

```python
def _resolve_editable_local_path(asset_path: str) -> Path:
    if str(asset_path).startswith(("http://", "https://")):
        return _materialize_remote_asset(asset_path)
    return Path(__file__).resolve().parent / asset_path
```

- [ ] **Step 4: 运行相关测试确认转绿**

Run: `pytest backend/tests/test_story_cover_api.py -k remote_cover -v`
Expected: PASS，远程 URL 也能进入需要本地文件的编辑链路。


### Task 7: 全面验证并补充文档注记

**Files:**
- Modify: `docs/superpowers/specs/2026-06-12-resource-url-storage-design.md`
- Test: `backend/tests/test_story_cover_api.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`
- Test: `frontend/src/api.test.ts`

- [ ] **Step 1: 运行后端封面测试**

Run: `pytest backend/tests/test_story_cover_api.py -v`
Expected: PASS

- [ ] **Step 2: 运行视频章节阶段测试中与故事版/视频资源相关的子集**

Run: `pytest backend/tests/test_video_chapter_stage_api.py -k "storyboard or video" -v`
Expected: PASS

- [ ] **Step 3: 运行前端资源 URL helper 测试**

Run: `npm test -- src/api.test.ts`
Expected: PASS

- [ ] **Step 4: 记录实现后验证结论到设计文档末尾**

```markdown
## Implementation Notes

- 封面已切换为优先保存 OSS URL
- 图片/视频资源入口已统一为“优先服务返回值”
- 前端 helper 已兼容完整 URL 与相对路径
```

- [ ] **Step 5: 完成一次手动冒烟验证**

Run:
- `生成一条封面`
- `生成一条故事版图`
- `生成一条视频资源`

Expected:
- 数据库字段与 API 回包一致
- 前端回显直接命中 OSS URL 或正确命中 `/static/...`
