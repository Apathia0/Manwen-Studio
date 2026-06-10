# 异步任务机制增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强现有异步任务机制，添加重试、状态持久化、并发控制、超时管理等功能

**Architecture:** 保持现有 asyncio.create_task 模式，通过 TaskManager 服务封装增强功能，新增 BackgroundTask 模型持久化任务状态

**Tech Stack:** Python/FastAPI, SQLAlchemy, asyncio, TypeScript/React

---

## 文件结构

### 新增文件
- `backend/services/task_manager.py` - TaskManager 服务，封装任务增强功能
- `backend/tests/test_task_manager.py` - TaskManager 单元测试

### 修改文件
- `backend/models.py` - 添加 BackgroundTask 模型
- `backend/main.py` - 集成 TaskManager 到现有任务
- `backend/routers/video.py` - 视频任务使用 TaskManager
- `backend/services/agent_service.py` - 批量操作添加并发限制
- `frontend/src/videoGenStore.ts` - 前端状态持久化
- `frontend/src/components/VideoPanel.tsx` - 视频轮询指数退避

---

## Task 1: 添加 BackgroundTask 模型

**Files:**
- Modify: `backend/models.py`
- Create: `backend/tests/test_task_manager.py`

- [ ] **Step 1: 编写 BackgroundTask 模型测试**

```python
# backend/tests/test_task_manager.py
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, BackgroundTask

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_background_task_create(db_session):
    """测试创建后台任务"""
    task = BackgroundTask(
        task_id="test_task_1",
        task_type="quality_check",
        status="pending",
        max_retries=3,
    )
    db_session.add(task)
    db_session.commit()
    
    saved = db_session.query(BackgroundTask).filter_by(task_id="test_task_1").first()
    assert saved is not None
    assert saved.status == "pending"
    assert saved.retry_count == 0
    assert saved.max_retries == 3

def test_background_task_status_update(db_session):
    """测试更新任务状态"""
    task = BackgroundTask(task_id="test_task_2", task_type="video_render")
    db_session.add(task)
    db_session.commit()
    
    task.status = "running"
    task.started_at = datetime.utcnow()
    db_session.commit()
    
    updated = db_session.query(BackgroundTask).filter_by(task_id="test_task_2").first()
    assert updated.status == "running"
    assert updated.started_at is not None

def test_background_task_retry(db_session):
    """测试重试计数"""
    task = BackgroundTask(
        task_id="test_task_3",
        task_type="quality_check",
        max_retries=3,
    )
    db_session.add(task)
    db_session.commit()
    
    task.retry_count = 1
    task.last_error = "Connection timeout"
    task.status = "retrying"
    db_session.commit()
    
    updated = db_session.query(BackgroundTask).filter_by(task_id="test_task_3").first()
    assert updated.retry_count == 1
    assert updated.last_error == "Connection timeout"
    assert updated.status == "retrying"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && python -m pytest tests/test_task_manager.py::test_background_task_create -v
```

预期: FAIL - `cannot import name 'BackgroundTask' from 'models'`

- [ ] **Step 3: 添加 BackgroundTask 模型**

```python
# backend/models.py - 在现有模型后添加

class BackgroundTask(Base):
    """后台任务状态持久化"""
    __tablename__ = "background_tasks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # 关联实体
    story_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # 元数据
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend && python -m pytest tests/test_task_manager.py -v
```

预期: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/models.py backend/tests/test_task_manager.py
git commit -m "feat: add BackgroundTask model for async task persistence"
```

---

## Task 2: 创建 TaskManager 服务

**Files:**
- Create: `backend/services/task_manager.py`
- Modify: `backend/tests/test_task_manager.py`

- [ ] **Step 1: 编写 TaskManager 测试**

```python
# backend/tests/test_task_manager.py - 添加测试

import asyncio
import pytest
from services.task_manager import TaskManager

@pytest.fixture
def task_manager():
    return TaskManager(max_concurrent=2)

def test_task_manager_init(task_manager):
    """测试 TaskManager 初始化"""
    assert task_manager._semaphore._value == 2
    assert len(task_manager._running_tasks) == 0

def test_with_retry_decorator(task_manager):
    """测试重试装饰器"""
    call_count = 0
    
    @task_manager.with_retry(max_retries=2, base_delay=0.01)
    async def failing_task():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Temporary error")
        return "success"
    
    result = asyncio.get_event_loop().run_until_complete(failing_task())
    assert result == "success"
    assert call_count == 3

def test_with_retry_exhausted(task_manager):
    """测试重试耗尽"""
    @task_manager.with_retry(max_retries=1, base_delay=0.01)
    async def always_failing():
        raise ValueError("Permanent error")
    
    with pytest.raises(ValueError, match="Permanent error"):
        asyncio.get_event_loop().run_until_complete(always_failing())
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && python -m pytest tests/test_task_manager.py::test_task_manager_init -v
```

预期: FAIL - `ModuleNotFoundError: No module named 'services.task_manager'`

- [ ] **Step 3: 创建 TaskManager 服务**

```python
# backend/services/task_manager.py

import asyncio
import logging
import uuid
from functools import wraps
from datetime import datetime, timedelta
from typing import Callable, Any, Optional
from database import SessionLocal
from models import BackgroundTask

logger = logging.getLogger(__name__)

class TaskManager:
    """轻量级任务管理器，提供重试、状态持久化、并发控制"""
    
    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict[str, asyncio.Task] = {}
    
    def with_retry(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ) -> Callable:
        """重试装饰器，支持指数退避"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                task_id = kwargs.get('task_id')
                last_exception = None
                
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt < max_retries:
                            delay = min(
                                base_delay * (exponential_base ** attempt),
                                max_delay
                            )
                            logger.warning(
                                f"Task {task_id} failed (attempt {attempt + 1}/{max_retries + 1}), "
                                f"retrying in {delay:.1f}s: {e}"
                            )
                            await asyncio.sleep(delay)
                            
                            if task_id:
                                self._update_task_retry(task_id, attempt + 1, str(e))
                        else:
                            logger.error(
                                f"Task {task_id} failed after {max_retries + 1} attempts: {e}"
                            )
                            if task_id:
                                self._mark_task_failed(task_id, str(e))
                            raise
                
                raise last_exception
            return wrapper
        return decorator
    
    def _update_task_retry(self, task_id: str, retry_count: int, error: str) -> None:
        """更新任务重试状态"""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                task.retry_count = retry_count
                task.last_error = error
                task.status = "retrying"
                db.commit()
        finally:
            db.close()
    
    def _mark_task_failed(self, task_id: str, error: str) -> None:
        """标记任务为失败"""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                task.status = "failed"
                task.error_message = error
                task.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    def _mark_task_succeeded(self, task_id: str, result: Any) -> None:
        """标记任务成功"""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                task.status = "succeeded"
                task.result_json = result if isinstance(result, dict) else {"result": result}
                task.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    def _create_task_record(
        self,
        task_id: str,
        task_type: str,
        max_retries: int,
        story_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        shot_id: Optional[int] = None,
    ) -> None:
        """创建任务记录"""
        db = SessionLocal()
        try:
            task = BackgroundTask(
                task_id=task_id,
                task_type=task_type,
                status="pending",
                max_retries=max_retries,
                story_id=story_id,
                chapter_id=chapter_id,
                shot_id=shot_id,
            )
            db.add(task)
            db.commit()
        finally:
            db.close()
    
    def _on_task_complete(self, task_id: str, task: asyncio.Task) -> None:
        """任务完成回调"""
        self._running_tasks.pop(task_id, None)
        
        if task.cancelled():
            self._mark_task_failed(task_id, "Task was cancelled")
        elif task.exception():
            self._mark_task_failed(task_id, str(task.exception()))
        else:
            self._mark_task_succeeded(task_id, task.result())
    
    async def submit_task(
        self,
        task_id: str,
        task_type: str,
        coro_func: Callable,
        *args,
        timeout: float = 300.0,
        max_retries: int = 3,
        story_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        shot_id: Optional[int] = None,
        **kwargs
    ) -> str:
        """提交任务到后台执行"""
        self._create_task_record(
            task_id, task_type, max_retries, story_id, chapter_id, shot_id
        )
        
        @self.with_retry(max_retries=max_retries)
        async def _wrapped_task():
            async with self._semaphore:
                try:
                    return await asyncio.wait_for(
                        coro_func(*args, task_id=task_id, **kwargs),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Task {task_id} timed out after {timeout}s")
                    raise
        
        task = asyncio.create_task(_wrapped_task())
        self._running_tasks[task_id] = task
        task.add_done_callback(lambda t: self._on_task_complete(task_id, t))
        
        # 更新状态为运行中
        db = SessionLocal()
        try:
            db_task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if db_task:
                db_task.status = "running"
                db_task.started_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        
        return task_id
    
    async def cleanup_stale_tasks(self, max_age_hours: int = 24) -> int:
        """清理超时的僵尸任务"""
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
            stale_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["pending", "running", "retrying"]),
                BackgroundTask.created_at < cutoff
            ).all()
            
            for task in stale_tasks:
                task.status = "failed"
                task.error_message = "Task timed out and was cleaned up"
                task.completed_at = datetime.utcnow()
                
                if task.task_id in self._running_tasks:
                    self._running_tasks[task.task_id].cancel()
            
            db.commit()
            return len(stale_tasks)
        finally:
            db.close()
    
    def get_task_status(self, task_id: str) -> Optional[dict]:
        """获取任务状态"""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if not task:
                return None
            
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": task.status,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "error_message": task.error_message,
                "result_json": task.result_json,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            }
        finally:
            db.close()

# 全局实例
task_manager = TaskManager(max_concurrent=5)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend && python -m pytest tests/test_task_manager.py -v
```

预期: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/task_manager.py backend/tests/test_task_manager.py
git commit -m "feat: add TaskManager service with retry and concurrency control"
```

---

## Task 3: 集成 TaskManager 到后台任务

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 导入 TaskManager**

```python
# backend/main.py - 在文件顶部导入

from services.task_manager import task_manager
```

- [ ] **Step 2: 改造 _background_quality_check**

```python
# backend/main.py - 找到 _background_quality_check 函数

# 原代码:
asyncio.create_task(_background_quality_check(
    story.id,
    str(story.description or "").strip(),
    _api_key,
    captured_tags,
    captured_chars,
    captured_outline,
))

# 改为:
task_manager.submit_task(
    task_id=f"quality_check_{story.id}_{int(datetime.utcnow().timestamp())}",
    task_type="quality_check",
    coro_func=_background_quality_check,
    story.id,
    str(story.description or "").strip(),
    _api_key,
    captured_tags,
    captured_chars,
    captured_outline,
    story_id=story.id,
    timeout=600,  # 10分钟超时
    max_retries=2,
)
```

- [ ] **Step 3: 添加任务状态查询 API**

```python
# backend/main.py - 添加新端点

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request):
    """查询后台任务状态"""
    user = _require_user(request, db)
    status = task_manager.get_task_status(task_id)
    if not status:
        raise HTTPException(404, "Task not found")
    return status

@app.get("/api/tasks")
async def list_tasks(
    request: Request,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """列出后台任务"""
    user = _require_user(request, db)
    db = SessionLocal()
    try:
        query = db.query(BackgroundTask)
        if status:
            query = query.filter(BackgroundTask.status == status)
        if task_type:
            query = query.filter(BackgroundTask.task_type == task_type)
        
        total = query.count()
        tasks = query.order_by(BackgroundTask.created_at.desc()).offset(offset).limit(limit).all()
        
        return {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "task_type": t.task_type,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()
```

- [ ] **Step 4: 添加定时清理任务**

```python
# backend/main.py - 添加启动事件

@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    # 启动定时清理任务
    async def cleanup_loop():
        while True:
            try:
                cleaned = await task_manager.cleanup_stale_tasks(max_age_hours=24)
                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} stale tasks")
            except Exception as e:
                logger.error(f"Task cleanup failed: {e}")
            await asyncio.sleep(3600)  # 每小时执行一次
    
    asyncio.create_task(cleanup_loop())
```

- [ ] **Step 5: 提交**

```bash
git add backend/main.py
git commit -m "feat: integrate TaskManager into background tasks"
```

---

## Task 4: 集成 TaskManager 到视频任务

**Files:**
- Modify: `backend/routers/video.py`

- [ ] **Step 1: 导入 TaskManager**

```python
# backend/routers/video.py - 在文件顶部导入

from services.task_manager import task_manager
```

- [ ] **Step 2: 改造视频任务提交**

```python
# backend/routers/video.py - 找到 submit_video_job 调用

# 原代码:
job_result = await video_gen_service.submit_video_job(...)

# 改为:
task_id = f"video_render_{shot_id}_{int(datetime.utcnow().timestamp())}"
job_result = await task_manager.submit_task(
    task_id=task_id,
    task_type="video_render",
    coro_func=video_gen_service.submit_video_job,
    shot_id=shot_id,
    provider=effective_provider,
    model=resolved_model,
    prompt=full_prompt,
    # ... 其他参数
    shot_id=shot_id,
    timeout=600,  # 10分钟超时
    max_retries=2,
)
```

- [ ] **Step 3: 提交**

```bash
git add backend/routers/video.py
git commit -m "feat: integrate TaskManager into video tasks"
```

---

## Task 5: 批量操作添加并发限制

**Files:**
- Modify: `backend/services/agent_service.py`

- [ ] **Step 1: 添加信号量限制**

```python
# backend/services/agent_service.py - 找到 batch_adjust_chapters 函数

# 原代码:
results = await asyncio.gather(*[_adjust_one(item) for item in chapters])

# 改为:
semaphore = asyncio.Semaphore(3)  # 限制并发为3

async def _adjust_one_with_limit(item: dict) -> dict:
    async with semaphore:
        return await _adjust_one(item)

results = await asyncio.gather(*[_adjust_one_with_limit(item) for item in chapters])
```

- [ ] **Step 2: 同样改造批量更新**

```python
# backend/services/agent_service.py - 找到 batch_update_chapters 函数

# 原代码:
results = await asyncio.gather(*[_update_one(item) for item in chapters])

# 改为:
semaphore = asyncio.Semaphore(3)

async def _update_one_with_limit(item: dict) -> dict:
    async with semaphore:
        return await _update_one(item)

results = await asyncio.gather(*[_update_one_with_limit(item) for item in chapters])
```

- [ ] **Step 3: 提交**

```bash
git add backend/services/agent_service.py
git commit -m "feat: add concurrency limit to batch operations"
```

---

## Task 6: 前端状态持久化

**Files:**
- Modify: `frontend/src/videoGenStore.ts`

- [ ] **Step 1: 添加持久化逻辑**

```typescript
// frontend/src/videoGenStore.ts

const STORAGE_KEY = 'video_gen_states';
const STATE_EXPIRY_MS = 24 * 60 * 60 * 1000; // 24小时

// 在文件顶部添加持久化函数
function loadPersistedStates(): Map<number, VideoGenState> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return new Map();
    
    const parsed = JSON.parse(stored);
    const now = Date.now();
    const states = new Map<number, VideoGenState>();
    
    for (const [shotId, state] of Object.entries(parsed)) {
      if (now - (state as VideoGenState).lastEventAt < STATE_EXPIRY_MS) {
        states.set(Number(shotId), state as VideoGenState);
      }
    }
    
    return states;
  } catch {
    return new Map();
  }
}

function persistStates(states: Map<number, VideoGenState>): void {
  try {
    const obj: Record<number, VideoGenState> = {};
    states.forEach((state, shotId) => {
      obj[shotId] = state;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    // localStorage可能已满，忽略错误
  }
}

// 修改 states 初始化
const states = loadPersistedStates();

// 修改 set 方法
set(shotId: number, state: VideoGenState) {
  states.set(shotId, { ...state, lastEventAt: Date.now() });
  persistStates(states);
  emit();
},

// 修改 patch 方法
patch(shotId: number, p: Partial<VideoGenState>) {
  const cur = states.get(shotId);
  if (!cur) return;
  states.set(shotId, { ...cur, ...p, lastEventAt: Date.now() });
  persistStates(states);
  emit();
},

// 修改 clear 方法
clear(shotId: number) {
  if (states.delete(shotId)) {
    persistStates(states);
    emit();
  }
},

// 添加清理过期状态方法
cleanupExpired() {
  const now = Date.now();
  let changed = false;
  
  states.forEach((state, shotId) => {
    if (now - state.lastEventAt > STATE_EXPIRY_MS) {
      states.delete(shotId);
      changed = true;
    }
  });
  
  if (changed) {
    persistStates(states);
    emit();
  }
},
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/videoGenStore.ts
git commit -m "feat: add frontend state persistence to videoGenStore"
```

---

## Task 7: 视频轮询指数退避

**Files:**
- Modify: `frontend/src/components/VideoPanel.tsx`

- [ ] **Step 1: 修改轮询逻辑**

```typescript
// frontend/src/components/VideoPanel.tsx - 找到 pollJobStatus 函数

// 原代码:
function pollJobStatus(jobId: number) {
  const poll = async () => {
    // ... 逻辑
    setTimeout(poll, 3000);
  };
  setTimeout(poll, 3000);
}

// 改为:
function pollJobStatus(jobId: number) {
  let delay = 3000;  // 初始3秒
  const maxDelay = 30000;  // 最大30秒
  
  const poll = async () => {
    try {
      const job = await getVideoJob(jobId);
      
      onJobsChange((prev) => prev.map((item) => (item.id === jobId ? job : item)));
      
      if (job.clip) {
        // ... 现有逻辑
      }
      
      // 指数退避
      if (job.status === 'running' || job.status === 'queued') {
        delay = Math.min(delay * 1.5, maxDelay);
        setTimeout(poll, delay);
      } else {
        // 完成或失败，重置延迟
        delay = 3000;
      }
    } catch (error) {
      // 错误时使用当前延迟重试
      setTimeout(poll, delay);
    }
  };
  
  setTimeout(poll, delay);
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/VideoPanel.tsx
git commit -m "feat: add exponential backoff to video polling"
```

---

## Task 8: 运行完整测试

**Files:**
- Test: `backend/tests/test_task_manager.py`

- [ ] **Step 1: 运行所有测试**

```bash
cd backend && python -m pytest tests/ -v
```

预期: 所有测试通过

- [ ] **Step 2: 检查代码风格**

```bash
cd backend && python -m flake8 services/task_manager.py --max-line-length=120
```

预期: 无警告

- [ ] **Step 3: 提交最终版本**

```bash
git add -A
git commit -m "feat: complete async task enhancement"
```

---

## 执行选项

**计划完成并保存到 `docs/superpowers/plans/2026-05-29-async-task-enhancement.md`**

两种执行方式：

1. **Subagent-Driven（推荐）** - 我为每个任务调度新的子代理，任务间进行审查，快速迭代

2. **Inline Execution** - 在当前会话中执行任务，批量执行并设置检查点

**选择哪种方式？**
