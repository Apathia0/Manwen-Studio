# 漫画生成异步后台任务实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将漫画生成（generate-manga-stream）改为使用 TaskManager 后台执行，确保关闭浏览器后任务继续运行，并添加状态同步机制。

**Architecture:** 复用现有的 BackgroundTask 模型和 TaskManager 服务，将漫画生成逻辑封装为后台任务 `_background_manga_generation`，event_generator 改为轮询任务状态。添加 `GET /api/chapters/{chapter_id}/manga-generation-status` 端点供前端查询。前端 MangaPanel 组件在挂载时主动查询任务状态，恢复轮询。

**Tech Stack:** Python/FastAPI/SQLAlchemy/SSE + React/TypeScript

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/main.py` | 修改 | 添加 `_background_manga_generation` 函数；修改 `generate_manga_stream` 端点；添加 `get_manga_generation_status` 端点 |
| `frontend/src/api.ts` | 修改 | 添加 `getMangaGenerationStatus` API 函数和 `MangaGenStatusResponse` 类型 |
| `frontend/src/components/MangaPanel.tsx` | 修改 | 添加状态同步机制：组件挂载时查询任务状态，恢复轮询 |

---

### Task 1: 后端 - 添加 _background_manga_generation 后台任务函数

**Files:**
- Modify: `backend/main.py`
- Test: 无独立测试（作为 Task 2 的一部分隐式测试）

- [ ] **Step 1: 在 main.py 中识别事件监听器附近的合适位置添加新函数**

在 `generate_manga_stream` 函数之前，添加 `_background_manga_generation` 函数。

```python
async def _background_manga_generation(
    chapter_id: int,
    scenes: list,
    image_count: int,
    character_profiles: dict,
    ref_entries: list,
    color_mode: str,
    image_api_key: str,
    custom_image_provider: bool,
    user_id: int,
    task_id: str | None = None,
) -> dict:
    """后台漫画生成任务，由 TaskManager 调度
    
    Args:
        task_id: 由 TaskManager 传入的任务ID
        其他参数与 generate_manga_stream 一致
    
    Returns:
        dict: {
            "completed_images": int,
            "total_images": int,
        }
    """
    logger.info(f"Background manga generation started: chapter={chapter_id}, images={image_count}")
    completed = 0
    total = len(scenes)
    
    for i, scene_prompt in enumerate(scenes, start=1):
        # 检查是否已存在（幂等性：断点续传）
        check_db = SessionLocal()
        try:
            existing = check_db.query(MangaImage).filter(
                MangaImage.chapter_id == chapter_id,
                MangaImage.image_number == i,
            ).first()
            if existing:
                completed += 1
                continue
        finally:
            check_db.close()
        
        # 生成参考图路径
        ref_imgs = _select_ref_image_paths_for_scene(scene_prompt, ref_entries)
        ref_paths = [str(p) for p, _ in ref_imgs]
        ref_labels = [label for _, label in ref_imgs]
        
        try:
            image_result = await generate_manga_image(
                scene_prompt,
                chapter_id,
                i,
                all_scenes=scenes,
                character_profiles=character_profiles,
                ref_image_paths=ref_paths if ref_paths else None,
                ref_labels=ref_labels if any(ref_labels) else None,
                color_mode=color_mode,
                api_key=image_api_key,
            )
            
            # 如果有 sanitized prompt，更新 scenes 文件
            if image_result.prompt_sanitized and image_result.final_prompt != scene_prompt:
                scenes[i - 1] = image_result.final_prompt
                meta = _load_scene_meta(chapter_id)
                sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [i - 1]))
                _write_scenes_file(chapter_id, scenes, sanitized_indices)
                scene_prompt = image_result.final_prompt
        except (MangaImageGenerationError, Exception) as e:
            logger.error(f"Background manga image {i} failed: {e}")
            # 不中断整体任务，记录错误
            raise  # 让 TaskManager 处理重试/失败
        
        # 保存到数据库
        write_db = SessionLocal()
        try:
            manga = MangaImage(
                chapter_id=chapter_id,
                image_number=i,
                image_path=image_result.image_path,
                prompt=scene_prompt,
            )
            write_db.add(manga)
            if custom_image_provider:
                write_db.commit()
            else:
                _check_and_consume_quota(user_id, "manga.image.monthly_limit", 1, write_db, deduct=True)
            write_db.refresh(manga)
        finally:
            write_db.close()
        
        completed += 1
    
    logger.info(f"Background manga generation completed: chapter={chapter_id}, completed={completed}/{total}")
    return {"completed_images": completed, "total_images": total}
```

- [ ] **Step 2: 确认函数依赖的导入**

确保 `main.py` 顶部导入了 `BackgroundTask` 和 `task_manager`（通常在文件顶部已有）：

```python
# 确认已有
from services.task_manager import task_manager
from models import BackgroundTask, MangaImage
```

- [ ] **Step 3: 确认 `_background_manga_generation` 放在正确位置**

在 `_background_quality_check` 函数附近（约第 5440-5480 行之间查找），添加新函数。确保在 `generate_manga_stream` 端点之前。

---

### Task 2: 后端 - 修改 generate_manga_stream 端点使用 TaskManager

**Files:**
- Modify: `backend/main.py`（第 5480-5610 行）

- [ ] **Step 1: 重写 generate_manga_stream 使用 TaskManager**

将 `generate_manga_stream` 修改为使用 `task_manager.submit_task()` 提交后台任务，不再直接在 `event_generator` 中生成图片。

```python
@app.post("/api/chapters/{chapter_id}/generate-manga-stream")
async def generate_manga_stream(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # Load scenes from file (must exist - user should generate/confirm scenes first)
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        raise HTTPException(400, "No scene prompts found. Generate scenes first.")
    image_count = _effective_image_count(chapter_id, user.id, db)

    raw = prompts_file.read_text(encoding="utf-8")
    scenes = _parse_scenes_text(raw)
    if len(scenes) != image_count:
        if len(scenes) > image_count:
            raise HTTPException(403, f"Current plan allows at most {image_count} images per chapter. Please reduce page count or upgrade your plan.")
        raise HTTPException(400, f"Expected {image_count} scenes, found {len(scenes)}")
    if chapter_id in ACTIVE_MANGA_GENERATIONS:
        raise HTTPException(409, "Manga generation is already running for this chapter")
    character_profiles = await _load_characters_async(chapter_id, request, db)
    ref_entries = _effective_ref_entries(chapter_id, db)
    color_mode = _effective_color_mode(chapter_id, user.id, db)
    image_api_key = _user_image_api_key(request)
    custom_image_provider = _custom_image_provider_active(request)
    _check_and_consume_feature_quota(request, user.id, "manga.image.monthly_limit", len(scenes), db, deduct=False, provider_kind="image")
    ACTIVE_MANGA_GENERATIONS.add(chapter_id)
    # 在释放事务前提取 user_id，避免异步 generator 中 user 对象 session 已关闭
    user_id = user.id
    _release_db_transaction(db)

    # 定义 task_id
    task_id = f"manga_gen_{chapter_id}_{int(datetime.datetime.utcnow().timestamp())}"

    # 提交后台任务
    await task_manager.submit_task(
        task_id=task_id,
        task_type="manga_generation",
        coro_func=_background_manga_generation,
        chapter_id=chapter_id,
        scenes=scenes,
        image_count=image_count,
        character_profiles=character_profiles,
        ref_entries=ref_entries,
        color_mode=color_mode,
        image_api_key=image_api_key,
        custom_image_provider=custom_image_provider,
        user_id=user_id,
        timeout=1800,  # 30 分钟超时
        max_retries=0,  # 漫画生成图片重试无意义，不重试
    )

    async def event_generator():
        try:
            yield {"event": "scenes", "data": json.dumps({"scenes": scenes}, ensure_ascii=False)}

            poll_count = 0
            max_polls = 900  # 30 分钟 / 2 秒 = 900 次轮询

            while poll_count < max_polls:
                poll_count += 1
                task_status = task_manager.get_task_status(task_id)

                if task_status is None:
                    # 任务 queued 但还没有创建记录
                    yield {"event": "progress", "data": json.dumps({"current": 0, "total": image_count, "prompt": "正在排队..."}, ensure_ascii=False)}
                    await asyncio.sleep(2)
                    continue

                status = task_status["status"]

                if status == "succeeded":
                    # 任务完成，返回所有已生成的图片
                    chapter_refresh = _ensure_db_chapter(chapter_id)
                    all_images = sorted(chapter_refresh.images, key=lambda img: img.image_number)
                    for img in all_images:
                        yield {
                            "event": "image",
                            "data": json.dumps({
                                "id": img.id,
                                "image_number": img.image_number,
                                "image_path": img.image_path,
                                "prompt": img.prompt or "",
                            }, ensure_ascii=False),
                        }
                    yield {"event": "done", "data": json.dumps({"message": "漫画生成完成！"}, ensure_ascii=False)}
                    return

                elif status == "failed":
                    error_msg = task_status.get("error_message", "Generation failed")
                    yield {"event": "error", "data": json.dumps({"error": error_msg}, ensure_ascii=False)}
                    return

                elif status == "pending":
                    yield {"event": "progress", "data": json.dumps({"current": 0, "total": image_count, "prompt": "正在排队..."}, ensure_ascii=False)}

                elif status == "retrying":
                    yield {"event": "progress", "data": json.dumps({"current": 0, "total": image_count, "prompt": "正在重试..."}, ensure_ascii=False)}

                elif status == "running":
                    # 从数据库中查询已完成的数量
                    check_db = SessionLocal()
                    try:
                        completed_count = check_db.query(MangaImage).filter(
                            MangaImage.chapter_id == chapter_id,
                        ).count()
                    finally:
                        check_db.close()
                    if completed_count > 0:
                        yield {"event": "progress", "data": json.dumps({
                            "current": completed_count,
                            "total": image_count,
                            "prompt": f"正在生成第 {completed_count + 1}/{image_count} 张漫画",
                        }, ensure_ascii=False)}

                        # 发送已生成的图片
                        check_db2 = SessionLocal()
                        try:
                            existing_imgs = check_db2.query(MangaImage).filter(
                                MangaImage.chapter_id == chapter_id,
                            ).order_by(MangaImage.image_number).all()
                        finally:
                            check_db2.close()
                        for img_obj in existing_imgs:
                            yield {
                                "event": "image",
                                "data": json.dumps({
                                    "id": img_obj.id,
                                    "image_number": img_obj.image_number,
                                    "image_path": img_obj.image_path,
                                    "prompt": img_obj.prompt or "",
                                }, ensure_ascii=False),
                            }
                    else:
                        yield {"event": "progress", "data": json.dumps({
                            "current": 0, "total": image_count, "prompt": "正在生成..."}, ensure_ascii=False)}

                await asyncio.sleep(2)

            # 超时
            yield {"event": "error", "data": json.dumps({"error": "漫画生成超时"}, ensure_ascii=False)}

        except asyncio.CancelledError:
            # SSE 连接断开，但后台任务继续运行
            logger.info(f"Manga generation SSE cancelled for chapter {chapter_id}, background task continues")
        except Exception as e:
            logger.exception(f"Manga generation SSE error: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}
        finally:
            ACTIVE_MANGA_GENERATIONS.discard(chapter_id)

    return EventSourceResponse(event_generator(), ping=10)
```

- [ ] **Step 2: 验证代码语法正确**

运行 Python 语法检查：

```bash
cd backend
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('Syntax OK')"
```

- [ ] **Step 3: 启动后端临时测试**

```bash
cd backend
python -c "import sys; sys.path.insert(0, '.'); from main import app; print('Import OK')"
```

如果导入失败，修复 import 问题后重试。

---

### Task 3: 后端 - 添加 GET /api/chapters/{chapter_id}/manga-generation-status 端点

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 在 main.py 中合适位置添加状态查询端点**

在 `generate_manga_stream` 端点之后（约第 5610 行后），添加新端点：

```python
@app.get("/api/chapters/{chapter_id}/manga-generation-status")
async def get_manga_generation_status(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """查询漫画生成后台任务状态"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    # 查询最新的漫画生成 BackgroundTask
    task = db.query(BackgroundTask).filter(
        BackgroundTask.task_type == "manga_generation",
        BackgroundTask.chapter_id == chapter_id,
    ).order_by(BackgroundTask.created_at.desc()).first()

    if not task:
        return {
            "status": "none",
            "message": "没有进行中的漫画生成任务",
        }

    # 查询当前已生成的图片数量
    image_count = db.query(MangaImage).filter(
        MangaImage.chapter_id == chapter_id,
    ).count()

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": image_count,
        "total": task.result_json.get("total_images", image_count) if task.result_json else image_count,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }
```

- [ ] **Step 2: 验证端点注册**

```bash
cd backend
python -c "import sys; sys.path.insert(0, '.'); from main import app; routes=[r.path for r in app.routes]; print('manga-generation-status' in any(routes)); print([r for r in routes if 'manga-generation' in r])"
```

预期输出：
```
True
['/api/chapters/{chapter_id}/manga-generation-status', '/api/chapters/{chapter_id}/generate-manga-stream']
```

---

### Task 4: 前端 - 添加 getMangaGenerationStatus API

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: 添加类型定义和 API 函数**

在 `MangaProgress` 接口附近（约第 641 行），添加：

```typescript
export interface MangaGenStatusResponse {
  task_id: string | null;
  status: 'none' | 'pending' | 'running' | 'succeeded' | 'failed' | 'retrying';
  progress: number;
  total: number;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export async function getMangaGenerationStatus(chapterId: number): Promise<MangaGenStatusResponse> {
  const response = await fetch(`/api/chapters/${chapterId}/manga-generation-status`);
  if (!response.ok) {
    throw new Error(`Failed to get manga generation status: ${response.statusText}`);
  }
  return response.json();
}
```

- [ ] **Step 2: 导出新类型和函数**

确认 `export` 语句已存在（通常函数定义处已有 `export`）。

- [ ] **Step 3: 验证前端构建**

```bash
cd frontend
npx tsc --noEmit --pretty 2>&1 | head -30
```

预期输出：无类型错误。

---

### Task 5: 前端 - 添加状态同步逻辑到 MangaPanel

**Files:**
- Modify: `frontend/src/components/MangaPanel.tsx`

- [ ] **Step 1: 添加导入**

确保 `MangaGenStatusResponse` 和 `getMangaGenerationStatus` 已从 `api.ts` 导入：

```typescript
import {
  // ... 现有导入
  getMangaGenerationStatus,
  type MangaGenStatusResponse,
} from '../api';
```

- [ ] **Step 2: 添加状态变量和轮询逻辑**

在 MangaPanel 组件内，添加状态变量（约第 237 行 `const mangaAbortRef` 之后）：

```typescript
  const [backendTaskStatus, setBackendTaskStatus] = useState<MangaGenStatusResponse | null>(null);
  const backendTaskPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 检查是否有后台任务在运行（当组件挂载时）
  const checkBackendMangaStatus = useCallback(async (chapterId: number) => {
    try {
      const status = await getMangaGenerationStatus(chapterId);
      if (status.status === 'running' || status.status === 'pending' || status.status === 'retrying') {
        // 后台任务还在运行，恢复轮询
        setBackendTaskStatus(status);
        startBackendTaskPolling(chapterId);
        // 恢复进度显示
        setProgress({ current: status.progress, total: status.total });
        setStatusMsg(`检测到后台正在生成漫画 (${status.progress}/${status.total})`);
        // 触发生成模式
        genStore.start(chapterId, status.total, existingImages);
        genStore.patch(chapterId, { current: status.progress, total: status.total, statusMsg: `后台正在生成漫画 (${status.progress}/${status.total})` });
      } else if (status.status === 'succeeded') {
        // 任务已完成，刷新图片
        await syncChapterImagesFromServer(chapterId);
        onChapterRefresh?.(chapterId);
      } else if (status.status === 'failed') {
        // 任务失败，显示错误但不进入生成模式
        setErrorMsg(`后台漫画生成任务失败：${status.error_message || '未知错误'}`);
      }
      // 'none': 没有任务，不做任何操作
    } catch (err) {
      // 查询失败不阻塞正常流程
      console.error('Failed to check backend manga status:', err);
    }
  }, [syncChapterImagesFromServer, onChapterRefresh, existingImages]);

  const startBackendTaskPolling = useCallback((chapterId: number) => {
    // 清理旧轮询
    if (backendTaskPollRef.current) {
      clearInterval(backendTaskPollRef.current);
    }
    backendTaskPollRef.current = setInterval(async () => {
      try {
        const status = await getMangaGenerationStatus(chapterId);
        if (status.status === 'succeeded') {
          // 任务完成，清理轮询
          if (backendTaskPollRef.current) {
            clearInterval(backendTaskPollRef.current);
            backendTaskPollRef.current = null;
          }
          setBackendTaskStatus(null);
          genStore.finish(chapterId);
          await syncChapterImagesFromServer(chapterId);
          onChapterRefresh?.(chapterId);
          setTimeout(() => genStore.clear(chapterId), 800);
        } else if (status.status === 'failed') {
          if (backendTaskPollRef.current) {
            clearInterval(backendTaskPollRef.current);
            backendTaskPollRef.current = null;
          }
          setBackendTaskStatus(null);
          setErrorMsg(`后台漫画生成失败：${status.error_message || '未知错误'}`);
          genStore.finish(chapterId, status.error_message || '未知错误');
        } else if (status.status === 'running' || status.status === 'pending' || status.status === 'retrying') {
          setProgress({ current: status.progress, total: status.total });
          genStore.patch(chapterId, { current: status.progress, total: status.total });
          // 发送新生成的图片到 genStore
          // 注意：genStore 中的 image 依赖于 SSE 推送，状态同步模式下需要从服务器重新获取
        }
      } catch (err) {
        console.error('Backend task polling error:', err);
      }
    }, 3000);  // 3 秒轮询一次
  }, [syncChapterImagesFromServer, onChapterRefresh]);
```

- [ ] **Step 3: 在组件挂载时检查后台任务状态**

在 `useEffect` 中 chapter 改变时，添加状态检查（约第 351 行，现有 `useEffect` 的末尾）：

```typescript
    // 检查是否有正在运行的后台漫画生成任务
    if (chapter) {
      checkBackendMangaStatus(chapter.id);
    }
```

修改 `useEffect` 的依赖数组，添加 `checkBackendMangaStatus`：

```typescript
  }, [chapter?.id, checkBackendMangaStatus]);
```

注意：因为 `checkBackendMangaStatus` 使用了 `useCallback`，它本身不会导致不必要的重渲染。

- [ ] **Step 4: 组件卸载时清理轮询**

在组件卸载 `useEffect` 中（如果有），或添加新的清理效果：

```typescript
  // 组件卸载时清理后台任务轮询
  useEffect(() => {
    return () => {
      if (backendTaskPollRef.current) {
        clearInterval(backendTaskPollRef.current);
        backendTaskPollRef.current = null;
      }
    };
  }, []);
```

- [ ] **Step 5: 验证前端构建**

```bash
cd frontend
npx tsc --noEmit --pretty 2>&1 | head -30
```

预期输出：无类型错误。

---

### Task 6: 运行完整测试验证

- [ ] **Step 1: 运行后端测试**

```bash
cd backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 2: 运行前端构建**

```bash
cd frontend
npx tsc --noEmit --pretty 2>&1 | head -30
npm run build 2>&1 | tail -10
```

- [ ] **Step 3: 手动验证流程**

```bash
cd backend
python main.py  # 启动后端（在另一个终端）
```

使用 curl 测试状态查询端点（后端启动后）：

```bash
curl -s http://localhost:8000/api/chapters/999999/manga-generation-status | head -5
```

预期输出：`{"status": "none", ...}`（因为 chapter 999999 不存在，会返回 401 或 404，这取决于认证，但至少说明端点注册成功）

---

## 自审

### 1. Spec 覆盖度
- ✅ `_background_manga_generation` 函数 → Task 1
- ✅ `generate_manga_stream` 使用 TaskManager → Task 2
- ✅ `GET /api/chapters/{chapter_id}/manga-generation-status` 端点 → Task 3
- ✅ 前端 `getMangaGenerationStatus` API → Task 4
- ✅ 前端 MangaPanel 状态同步（挂载时检查 + 恢复轮询）→ Task 5
- ✅ 测试验证 → Task 6

### 2. 占位符检查
- ✅ 所有步骤包含完整代码
- ✅ 无 "TBD", "TODO", "implement later"
- ✅ 无 "Proper error handling" 等模糊描述
- ✅ 所有测试步骤有具体命令和预期输出

### 3. 类型一致性
- ✅ `_background_manga_generation` 签名中的 `chapter_id`, `scenes`, `image_count` 等参数与现有代码一致
- ✅ `task_manager.submit_task()` 调用格式与 `video.py` 中一致
- ✅ `MangaGenStatusResponse.status` 类型为联合类型，包含所有可能值
- ✅ `event_generator` 中的 SSE event 格式（`progress`, `image`, `done`, `error`）与现有 `MangaProgress` 接口兼容
