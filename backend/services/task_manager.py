import asyncio
import logging
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Callable, Any, Optional
from database import SessionLocal
from models import BackgroundTask
from services.errors import MissingApiKeyError

logger = logging.getLogger(__name__)


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class TaskManager:
    """Lightweight background task manager with retries and persisted status."""

    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._cancellation_flags: dict[str, bool] = {}

    def _should_retry_exception(self, exc: Exception) -> bool:
        retryable = getattr(exc, "retryable", None)
        if retryable is not None:
            return bool(retryable)
        if isinstance(exc, (asyncio.CancelledError, asyncio.TimeoutError, MissingApiKeyError, ValueError)):
            return False

        msg = str(exc).lower()
        non_retry_terms = (
            "api key", "auth", "unauthorized", "forbidden", "quota",
            "content policy", "invalid request", "401", "403", "400",
            "鉴权", "认证", "未配置", "不能为空", "额度", "风控",
        )
        if any(term in msg for term in non_retry_terms):
            return False

        retry_terms = (
            "timeout", "timed out", "rate limit", "too many requests",
            "temporar", "service unavailable", "network", "transport",
            "connection", "429", "500", "502", "503", "504",
            "超时", "网络", "限流", "暂时", "稍后",
        )
        return any(term in msg for term in retry_terms)

    def _merge_task_metadata(self, task: BackgroundTask, metadata: dict[str, Any] | None) -> None:
        if not metadata:
            return
        current = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        task.metadata_json = {**current, **metadata}

    def update_task_metadata(self, task_id: str | None, **metadata: Any) -> None:
        if not task_id:
            return
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                self._merge_task_metadata(task, metadata)
                db.commit()
        finally:
            db.close()

    def _mark_task_running(self, task_id: str, metadata: dict[str, Any] | None = None) -> None:
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task and task.status != "failed":
                task.status = "running"
                if not task.started_at:
                    task.started_at = _now_naive()
                merged = {"stage": "running", "next_retry_at": None}
                if metadata:
                    merged.update(metadata)
                self._merge_task_metadata(task, merged)
                db.commit()
        finally:
            db.close()

    def with_retry(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        task_id: str | None = None,
    ) -> Callable:
        """Retry decorator with task metadata updates."""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                runtime_task_id = task_id or kwargs.get('task_id')
                last_exception = None

                for attempt in range(max_retries + 1):
                    try:
                        if runtime_task_id and attempt > 0:
                            self._mark_task_running(
                                runtime_task_id,
                                {
                                    "stage": "running",
                                    "message": f"正在进行第 {attempt + 1} 次尝试...",
                                    "next_retry_at": None,
                                },
                            )
                        return await func(*args, **kwargs)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        if isinstance(e, asyncio.TimeoutError) or not self._should_retry_exception(e):
                            if runtime_task_id:
                                self._mark_task_failed(runtime_task_id, str(e))
                            raise
                        last_exception = e
                        if attempt < max_retries:
                            delay = min(
                                base_delay * (exponential_base ** attempt),
                                max_delay,
                            )
                            next_retry = _now_naive() + timedelta(seconds=delay)
                            logger.warning(
                                f"Task {runtime_task_id} failed (attempt {attempt + 1}/{max_retries + 1}), "
                                f"retrying in {delay:.1f}s: {e}"
                            )
                            if runtime_task_id:
                                self._update_task_retry(runtime_task_id, attempt + 1, str(e), next_retry)
                            await asyncio.sleep(delay)
                        else:
                            logger.error(
                                f"Task {runtime_task_id} failed after {max_retries + 1} attempts: {e}"
                            )
                            if runtime_task_id:
                                self._mark_task_failed(runtime_task_id, str(e))
                            raise

                raise last_exception
            return wrapper
        return decorator

    def _update_task_retry(
        self,
        task_id: str,
        retry_count: int,
        error: str,
        next_retry_at: datetime | None = None,
    ) -> None:
        """Update task retry state."""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                task.retry_count = retry_count
                task.error_message = error
                task.status = "retrying"
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "retrying",
                        "message": f"上游服务暂时不可用，正在自动重试 ({retry_count}/{task.max_retries})...",
                        "last_error": error,
                        "next_retry_at": _iso(next_retry_at),
                    },
                )
                db.commit()
        finally:
            db.close()

    def _mark_task_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                # Preserve an existing failed state, for example user cancellation.
                if task.status == "failed":
                    return
                task.status = "failed"
                task.error_message = error
                task.completed_at = _now_naive()
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "failed",
                        "message": error,
                        "last_error": error,
                        "next_retry_at": None,
                    },
                )
                db.commit()
        finally:
            db.close()

    def _mark_task_succeeded(self, task_id: str, result: Any) -> None:
        """Mark task as succeeded."""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                # Do not overwrite a failed/cancelled task.
                if task.status == "failed":
                    return
                task.status = "succeeded"
                task.result_json = result if isinstance(result, dict) else {"result": result}
                task.completed_at = _now_naive()
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "succeeded",
                        "message": "任务已完成",
                        "next_retry_at": None,
                    },
                )
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
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Create a persisted task record."""
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
                metadata_json=metadata,
            )
            db.add(task)
            db.commit()
        finally:
            db.close()

    def _on_task_complete(self, task_id: str, task: asyncio.Task) -> None:
        """Task completion callback."""
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
        metadata: Optional[dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """Submit a coroutine to run in the background."""
        initial_metadata = {"stage": "queued", "message": "任务已排队，等待执行..."}
        if metadata:
            initial_metadata.update(metadata)
        self._create_task_record(
            task_id, task_type, max_retries, story_id, chapter_id, shot_id, initial_metadata
        )

        @self.with_retry(max_retries=max_retries, task_id=task_id)
        async def _wrapped_task():
            async with self._semaphore:
                try:
                    self._mark_task_running(
                        task_id,
                        {
                            "stage": initial_metadata.get("running_stage", "running"),
                            "message": initial_metadata.get("running_message", "任务正在执行..."),
                        },
                    )
                    coro = coro_func(*args, task_id=task_id, story_id=story_id, chapter_id=chapter_id, shot_id=shot_id, **kwargs)
                    if timeout is None:
                        return await coro
                    return await asyncio.wait_for(coro, timeout=timeout)
                except asyncio.TimeoutError:
                    logger.error(f"Task {task_id} timed out after {timeout}s")
                    raise

        task = asyncio.create_task(_wrapped_task())
        self._running_tasks[task_id] = task
        task.add_done_callback(lambda t: self._on_task_complete(task_id, t))

        return task_id

    def request_cancellation(self, task_id: str) -> bool:
        """Request graceful cancellation for a running task."""


        task = self._running_tasks.get(task_id)
        if task is None:
            return False
        self._cancellation_flags[task_id] = True
        return True

    def request_cancellation_by_prefix(self, task_id_prefix: str) -> list[str]:
        """Request graceful cancellation for all running tasks with the prefix."""
        matched = [
            task_id
            for task_id in self._running_tasks
            if task_id.startswith(task_id_prefix)
        ]
        for task_id in matched:
            self._cancellation_flags[task_id] = True
        return matched

    def is_cancellation_requested(self, task_id: str | None) -> bool:
        """Check whether graceful cancellation was requested."""
        if task_id is None:
            return False
        return self._cancellation_flags.get(task_id, False)

    def clear_cancellation_flag(self, task_id: str) -> None:
        """Clear cancellation flag."""
        self._cancellation_flags.pop(task_id, None)

    def cancel_task(self, task_id: str) -> bool:
        """Hard-cancel a running asyncio task."""
        task = self._running_tasks.get(task_id)
        if task is None:
            return False
        task.cancel()
        return True

    def cleanup_stale_tasks(self, max_age_hours: int = 24) -> int:
        """Clean up stale pending/running/retrying tasks."""
        db = SessionLocal()
        try:
            cutoff = _now_naive() - timedelta(hours=max_age_hours)
            stale_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["pending", "running", "retrying"]),
                BackgroundTask.created_at < cutoff
            ).all()

            for task in stale_tasks:
                task.status = "failed"
                task.error_message = "任务超时已清理"
                task.completed_at = _now_naive()
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "failed",
                        "message": "任务超时已清理",
                        "next_retry_at": None,
                    },
                )

                if task.task_id in self._running_tasks:
                    self._running_tasks[task.task_id].cancel()

            db.commit()
            return len(stale_tasks)
        finally:
            db.close()

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get persisted task status."""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if not task:
                return None

            metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": task.status,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "error_message": task.error_message,
                "result_json": task.result_json,
                "metadata_json": metadata,
                "stage": metadata.get("stage"),
                "message": metadata.get("message"),
                "next_retry_at": metadata.get("next_retry_at"),
                "created_at": _iso(task.created_at),
                "started_at": _iso(task.started_at),
                "completed_at": _iso(task.completed_at),
            }
        finally:
            db.close()


# Global singleton
task_manager = TaskManager(max_concurrent=5)
