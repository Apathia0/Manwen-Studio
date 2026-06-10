# 漫画生成后台任务设计

## 概述

本设计旨在解决漫画生成任务在浏览器关闭后中断的问题，通过复用 BackgroundTask 模型和 TaskManager 服务，实现：
1. 漫画生成任务在后台持续运行
2. 用户重新打开页面时自动恢复状态
3. 统一的任务状态管理

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│  前端（浏览器）                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  SSE 连接 ← event_generator 轮询进度            │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                          │
                          │ 关闭浏览器 → SSE 连接断开
                          ▼
┌─────────────────────────────────────────────────────────┐
│  后端                                                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │  event_generator（已取消）                       │   │
│  │  ├── 轮询 task_manager.get_task_status()        │   │
│  │  └── 返回进度和结果                              │   │
│  └─────────────────────────────────────────────────┘   │
│                          × 被取消                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │  asyncio.Task（继续运行）                        │   │
│  │  ├── 逐张生成漫画图片                            │   │
│  │  ├── 保存到 MangaImage 表                        │   │
│  │  └── 更新 BackgroundTask 状态                    │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## 核心改动

### 1. 封装漫画生成为后台任务

**文件**: `backend/main.py`

**新增函数**: `_background_manga_generation`

**职责**:
- 逐张生成漫画图片
- 保存到 MangaImage 表
- 更新任务进度（通过 result_json）

**接口**:
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
    """
    后台漫画生成任务
    
    Returns:
        dict: {
            "completed_images": int,
            "total_images": int,
            "images": list[dict],  # 生成的图片信息
        }
    """
```

**关键逻辑**:
1. 遍历 scenes 列表
2. 检查 MangaImage 表是否已存在该图片
3. 如果不存在，调用 `generate_manga_image()` 生成
4. 保存到 MangaImage 表
5. 更新 result_json 中的进度

### 2. 修改 event_generator

**文件**: `backend/main.py`

**修改函数**: `generate_manga_stream`

**改动**:
1. 使用 `task_manager.submit_task()` 提交后台任务
2. `event_generator` 只负责轮询进度和返回结果
3. SSE 连接断开时，后台任务继续运行

**代码结构**:
```python
async def event_generator():
    try:
        # 提交后台任务
        task_id = f"manga_gen_{chapter_id}_{int(datetime.datetime.utcnow().timestamp())}"
        await task_manager.submit_task(
            task_id=task_id,
            task_type="manga_generation",
            coro_func=_background_manga_generation,
            ...
        )
        
        # 轮询任务状态
        while True:
            task_status = task_manager.get_task_status(task_id)
            # ... 返回进度和结果
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        # SSE 连接断开，但后台任务继续运行
        pass
```

### 3. 添加状态查询 API

**文件**: `backend/main.py`

**新增端点**: `GET /api/chapters/{chapter_id}/manga-generation-status`

**职责**:
- 查询指定章节的漫画生成任务状态
- 返回任务进度和结果

**接口**:
```python
@app.get("/api/chapters/{chapter_id}/manga-generation-status")
async def get_manga_generation_status(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db)
) -> dict:
    """
    查询漫画生成任务状态
    
    Returns:
        dict: {
            "task_id": str | None,
            "status": str,  # none/pending/running/succeeded/failed
            "progress": int,
            "total": int,
            "error_message": str | None,
            "created_at": str | None,
            "completed_at": str | None,
        }
    """
```

**查询逻辑**:
1. 查询 BackgroundTask 表
2. 筛选条件：task_type == "manga_generation" AND chapter_id == chapter_id
3. 按 created_at 降序排列，取最新一条
4. 返回任务状态

### 4. 前端状态同步

**文件**: `frontend/src/components/MangaPanel.tsx`（或现有组件）

**新增功能**:
1. 组件挂载时查询任务状态
2. 如果任务还在运行，恢复轮询
3. 如果任务已完成，刷新图片列表
4. 如果任务失败，显示错误

**代码结构**:
```typescript
const checkMangaGenerationStatus = async (chapterId: number) => {
  const response = await fetch(`/api/chapters/${chapterId}/manga-generation-status`);
  const data = await response.json();
  
  if (data.status === "running" || data.status === "pending") {
    // 恢复轮询
    setMangaGenStatus(data);
    startMangaStatusPolling(chapterId);
  } else if (data.status === "succeeded") {
    // 刷新图片列表
    setMangaGenStatus(null);
    refreshImages(chapterId);
  } else if (data.status === "failed") {
    // 显示错误
    setMangaGenStatus({ ...data, error: data.error_message });
  }
};

useEffect(() => {
  if (chapterId) {
    checkMangaGenerationStatus(chapterId);
  }
}, [chapterId]);
```

## 数据流

```
用户请求生成漫画
    ↓
提交后台任务 → task_manager.submit_task()
    ↓
event_generator 轮询进度
    ↓
┌─ 用户关闭浏览器 ──────────────────────────────┐
│  SSE 连接断开                                 │
│  event_generator 被取消                       │
│  但 asyncio.Task 继续运行                     │
└───────────────────────────────────────────────┘
    ↓
用户重新打开页面
    ↓
前端查询任务状态 → GET /api/chapters/{id}/manga-generation-status
    ↓
┌─ 任务状态 ────────────────────────────────────┐
│  running → 恢复轮询                           │
│  succeeded → 刷新图片列表                      │
│  failed → 显示错误                             │
│  none → 正常状态                               │
└───────────────────────────────────────────────┘
```

## 关键设计点

| 设计点 | 说明 |
|--------|------|
| **任务粒度** | 每张图片作为独立的子任务，支持断点续传 |
| **进度更新** | 通过 result_json 存储 completed_images 和 total_images |
| **状态同步** | 前端组件挂载时查询任务状态，恢复轮询 |
| **错误处理** | 单张图片失败不影响其他图片，记录错误继续执行 |
| **幂等性** | 已生成的图片跳过，支持断点续传 |
| **超时设置** | 漫画生成任务超时 30 分钟（1800 秒） |
| **重试策略** | 漫画生成不重试（max_retries=0） |

## 依赖关系

- **BackgroundTask 模型**: 已存在，用于存储任务状态
- **TaskManager 服务**: 已存在，用于管理后台任务
- **MangaImage 模型**: 已存在，用于存储漫画图片

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 任务超时 | 30 分钟内未完成 | 监控任务执行时间，必要时调整超时 |
| 数据库连接池压力 | 大量并发任务 | 使用连接池，限制并发数 |
| 前端状态不一致 | 用户看到过时状态 | 组件挂载时主动查询状态 |

## 测试策略

### 单元测试

1. `_background_manga_generation` 函数
   - 测试正常生成流程
   - 测试断点续传（已存在的图片跳过）
   - 测试错误处理

2. `get_manga_generation_status` 端点
   - 测试查询存在的任务
   - 测试查询不存在的任务
   - 测试不同状态的任务

### 集成测试

1. 完整流程测试
   - 提交任务 → 关闭浏览器 → 重新打开 → 检查状态
   - 验证任务在后台继续运行
   - 验证前端状态同步

2. 边界条件测试
   - 并发生成多个章节的漫画
   - 任务超时处理
   - 网络断开恢复

## 部署考虑

### 数据库迁移

无需迁移，使用现有的 BackgroundTask 表。

### 配置参数

```python
# 环境变量
MANGA_GENERATION_TIMEOUT=1800  # 30分钟
MANGA_GENERATION_POLL_INTERVAL=2  # 2秒轮询一次
```

### 监控指标

- 任务成功率
- 平均生成时间
- 任务超时率
- 并发任务数

---

**设计完成日期**: 2026-05-30
**设计者**: Sisyphus
**状态**: 待审查
