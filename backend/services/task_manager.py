import asyncio
import logging
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Callable, Any, Optional
from database import SessionLocal
from models import BackgroundTask

logger = logging.getLogger(__name__)


class TaskManager:
    """轻量级任务管理器，提供重试、状态持久化、并发控制"""

    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._cancellation_flags: dict[str, bool] = {}

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
                    except asyncio.CancelledError:
                        # 任务取消直接重抛，不重试
                        raise
                    except Exception as e:
                        # 超时异常直接抛出不重试
                        if isinstance(e, asyncio.TimeoutError):
                            raise
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
                task.error_message = error
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
                # 如果已经是 failed 状态，保留已有的错误消息（例如取消任务已设置的信息）
                if task.status == "failed":
                    return
                task.status = "failed"
                task.error_message = error
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
                # 如果已经是 failed（如已被用户取消），不再覆盖
                if task.status == "failed":
                    return
                task.status = "succeeded"
                task.result_json = result if isinstance(result, dict) else {"result": result}
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
                        coro_func(*args, task_id=task_id, story_id=story_id, chapter_id=chapter_id, shot_id=shot_id, **kwargs),
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
                db_task.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
        finally:
            db.close()

        return task_id

    def request_cancellation(self, task_id: str) -> bool:
        """请求优雅取消正在运行的任务。

        设置取消标志，由业务协程在合适的时机（如每轮循环开始前）检查。
        不会粗暴地抛 CancelledError 中断正在进行的 await 操作，
        因此当前正在生成中的图片可以正常完成。
        """
        task = self._running_tasks.get(task_id)
        if task is None:
            return False
        self._cancellation_flags[task_id] = True
        return True

    def is_cancellation_requested(self, task_id: str | None) -> bool:
        """检查任务是否被请求取消"""
        if task_id is None:
            return False
        return self._cancellation_flags.get(task_id, False)

    def clear_cancellation_flag(self, task_id: str) -> None:
        """清除取消标志"""
        self._cancellation_flags.pop(task_id, None)

    def cancel_task(self, task_id: str) -> bool:
        """硬取消 — 直接抛 CancelledError 中断 await（备用方案）"""
        task = self._running_tasks.get(task_id)
        if task is None:
            return False
        task.cancel()
        return True

    def cleanup_stale_tasks(self, max_age_hours: int = 24) -> int:
        """清理超时的僵尸任务"""
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max_age_hours)
            stale_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["pending", "running", "retrying"]),
                BackgroundTask.created_at < cutoff
            ).all()

            for task in stale_tasks:
                task.status = "failed"
                task.error_message = "任务超时已清理"
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)

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
