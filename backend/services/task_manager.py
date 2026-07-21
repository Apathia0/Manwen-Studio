import asyncio
import logging
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Callable, Any, Optional
from sqlalchemy import and_, or_
from database import SessionLocal
from models import BackgroundTask
from services.errors import MissingApiKeyError, public_error_message

logger = logging.getLogger(__name__)

_TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled", "canceled"}


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
            "content policy", "invalid request", "401", "400",
            "鉴权", "认证", "未配置", "不能为空", "额度", "风控",
        )
        if any(term in msg for term in non_retry_terms):
            return False

        retry_terms = (
            "timeout", "timed out", "rate limit", "too many requests",
            "temporar", "service unavailable", "network", "transport",
            "connection", "403", "429", "500", "502", "503", "504",
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
            if task and task.status not in _TERMINAL_TASK_STATUSES and task.status != "cancel_requested":
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
                                self._mark_task_failed(runtime_task_id, e)
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
                                self._update_task_retry(runtime_task_id, attempt + 1, e, next_retry)
                            await asyncio.sleep(delay)
                        else:
                            logger.error(
                                f"Task {runtime_task_id} failed after {max_retries + 1} attempts: {e}"
                            )
                            if runtime_task_id:
                                self._mark_task_failed(runtime_task_id, e)
                            raise

                raise last_exception
            return wrapper
        return decorator

    def _update_task_retry(
        self,
        task_id: str,
        retry_count: int,
        error: object,
        next_retry_at: datetime | None = None,
    ) -> None:
        """Update task retry state."""
        public_error = public_error_message(error)
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task and task.status not in _TERMINAL_TASK_STATUSES and task.status != "cancel_requested":
                task.retry_count = retry_count
                task.error_message = public_error
                task.status = "retrying"
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "retrying",
                        "message": f"上游服务暂时不可用，正在自动重试 ({retry_count}/{task.max_retries})...",
                        "last_error": public_error,
                        "next_retry_at": _iso(next_retry_at),
                    },
                )
                db.commit()
        finally:
            db.close()

    def _mark_task_failed(self, task_id: str, error: object) -> None:
        """Mark task as failed."""
        public_error = public_error_message(error)
        error_code = str(getattr(error, "code", "") or "task_failed")
        retryable = bool(getattr(error, "retryable", False))
        suggestion = str(getattr(error, "suggestion", "") or "").strip()
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == task_id
            ).first()
            if task:
                # Preserve an existing failed state, for example user cancellation.
                if task.status in _TERMINAL_TASK_STATUSES:
                    return
                task.status = "failed"
                task.error_message = public_error
                task.completed_at = _now_naive()
                self._finalize_failed_task_billing(task, db)
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "failed",
                        "message": public_error,
                        "last_error": public_error,
                        "error_code": error_code,
                        "retryable": retryable,
                        "suggestion": suggestion or None,
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
                if task.status in _TERMINAL_TASK_STATUSES or task.status == "cancel_requested":
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

    def _mark_task_cancelled(self, task_id: str, message: str) -> None:
        """将任务标记为已取消，且不覆盖其他终态。"""
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
            if not task or task.status in _TERMINAL_TASK_STATUSES:
                return
            self._finalize_failed_task_billing(task, db)
            task.status = "cancelled"
            task.error_message = message
            task.completed_at = _now_naive()
            self._merge_task_metadata(
                task,
                {
                    "stage": "cancelled",
                    "message": message,
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
        quota_user_id: Optional[int] = None,
        quota_feature_key: Optional[str] = None,
        quota_amount: int = 0,
        quota_period_key: Optional[str] = None,
        quota_usage_event_id: Optional[int] = None,
    ) -> None:
        """Create a persisted task record."""
        db = SessionLocal()
        try:
            task_metadata = dict(metadata or {})
            if quota_usage_event_id:
                task_metadata["billing_usage_event_id"] = int(quota_usage_event_id)
            task = BackgroundTask(
                task_id=task_id,
                task_type=task_type,
                status="pending",
                max_retries=max_retries,
                story_id=story_id,
                chapter_id=chapter_id,
                shot_id=shot_id,
                metadata_json=task_metadata,
                quota_user_id=quota_user_id,
                quota_feature_key=quota_feature_key,
                quota_amount=quota_amount,
                quota_period_key=quota_period_key,
            )
            db.add(task)
            db.commit()
        finally:
            db.close()

    def _on_task_complete(self, task_id: str, task: asyncio.Task) -> None:
        """Task completion callback."""
        self._running_tasks.pop(task_id, None)
        self._cancellation_flags.pop(task_id, None)

        if task.cancelled():
            self._mark_task_cancelled(task_id, "任务已取消")
        elif task.exception():
            self._mark_task_failed(task_id, task.exception())
        else:
            result = task.result()
            result_status = str(result.get("status") or "").lower() if isinstance(result, dict) else ""
            workflow_status = str(result.get("workflow_status") or "").lower() if isinstance(result, dict) else ""
            result_failed = bool(
                isinstance(result, dict)
                and (
                    result.get("success") is False
                    or result_status in {"cancelled", "canceled", "failed"}
                    or workflow_status in {"cancelled", "canceled", "failed"}
                    or bool(result.get("error"))
                )
            )
            if result_status in {"cancelled", "canceled"} or workflow_status in {"cancelled", "canceled"}:
                self._mark_task_cancelled(
                    task_id,
                    str(result.get("message") or workflow_status or result_status or "任务已取消"),
                )
            elif result_failed:
                self._mark_task_failed(
                    task_id,
                    str(result.get("error") or result.get("message") or workflow_status or result_status or "任务失败"),
                )
            else:
                self._mark_task_succeeded(task_id, result)

    def refund_quota(
        self,
        user_id: int,
        feature_key: str,
        amount: int,
        db,
        period_key: Optional[str] = None,
        *,
        usage_event_id: Optional[int] = None,
    ) -> None:
        """按任务绑定的用量事件幂等退款，不再按特性和数量猜测金额。"""
        if not usage_event_id:
            logger.warning(
                "忽略缺少用量事件的任务退款 user=%s feature=%s amount=%s",
                user_id,
                feature_key,
                amount,
            )
            return
        from services.ai.resolver import refund_ai_call

        refund_ai_call(db, usage_event_id, error_code="background_task_failed", commit=False)

    def _finalize_failed_task_billing(self, task: BackgroundTask, db) -> None:
        """失败任务有部分漫画产物时按实际数量结算，否则释放原预扣。"""
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        analysis_usage_event_id = int(metadata.get("analysis_billing_usage_event_id") or 0)
        if task.task_type == "manga_generation" and analysis_usage_event_id:
            from models import Chapter
            from services.ai.resolver import complete_ai_call_by_usage_event

            chapter = db.get(Chapter, task.chapter_id) if task.chapter_id else None
            analysis = chapter.manga_asset_analysis_json if chapter and isinstance(chapter.manga_asset_analysis_json, dict) else {}
            analysis_completed = bool(
                analysis.get("status") == "ready"
                and analysis.get("input_hash") == metadata.get("asset_analysis_hash")
            )
            complete_ai_call_by_usage_event(
                db,
                analysis_usage_event_id,
                success=analysis_completed,
                # 无法恢复供应商 usage 时传 0，计费层会回退到持久化 estimated_points。
                input_tokens=0,
                output_tokens=0,
                error_code=None if analysis_completed else "background_task_failed",
                usage_source="database_recovery",
                commit=False,
            )
            self._merge_task_metadata(task, {"analysis_billing_usage_event_id": 0})

        asset_usage_event_id = int(metadata.get("asset_billing_usage_event_id") or 0)
        if task.task_type == "manga_generation" and asset_usage_event_id:
            from models import MangaAsset
            from services.ai.resolver import complete_ai_call_by_usage_event

            generated_assets = db.query(MangaAsset).filter(
                MangaAsset.chapter_id == task.chapter_id,
                MangaAsset.status == "active",
            ).all()
            generated_count = sum(
                1
                for asset in generated_assets
                if isinstance(asset.metadata_json, dict)
                and asset.metadata_json.get("generation_task_id") == task.task_id
            )
            complete_ai_call_by_usage_event(
                db,
                asset_usage_event_id,
                success=True,
                image_count=generated_count,
                usage_source="database_recovery",
                commit=False,
            )
            self._merge_task_metadata(
                task,
                {
                    "asset_billing_usage_event_id": 0,
                    "asset_generated": generated_count,
                },
            )

        usage_event_id = int(metadata.get("billing_usage_event_id") or 0)
        if not usage_event_id:
            return

        initial_numbers = metadata.get("initial_existing_numbers")
        if task.task_type == "manga_generation" and task.chapter_id and isinstance(initial_numbers, list):
            from models import MangaImage
            from services.ai.resolver import complete_ai_call_by_usage_event

            initial_set = {int(value) for value in initial_numbers}
            current_numbers = {
                int(row[0])
                for row in db.query(MangaImage.image_number).filter(
                    MangaImage.chapter_id == task.chapter_id,
                ).all()
            }
            generated_count = len(current_numbers - initial_set)
            complete_ai_call_by_usage_event(
                db,
                usage_event_id,
                success=True,
                image_count=generated_count,
                usage_source="database_recovery",
                commit=False,
            )
            self._merge_task_metadata(
                task,
                {
                    "billing_usage_event_id": 0,
                    "billing_settled_images": generated_count,
                },
            )
            return

        if task.quota_user_id and task.quota_feature_key:
            self.refund_quota(
                task.quota_user_id,
                task.quota_feature_key,
                task.quota_amount or 0,
                db,
                task.quota_period_key,
                usage_event_id=usage_event_id,
            )

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
        quota_user_id: Optional[int] = None,
        quota_feature_key: Optional[str] = None,
        quota_amount: int = 0,
        quota_period_key: Optional[str] = None,
        quota_usage_event_id: Optional[int] = None,
        **kwargs
    ) -> str:
        """Submit a coroutine to run in the background."""
        initial_metadata = {"stage": "queued", "message": "任务已排队，等待执行..."}
        if metadata:
            initial_metadata.update(metadata)
        self._create_task_record(
            task_id, task_type, max_retries, story_id, chapter_id, shot_id,
            initial_metadata, quota_user_id, quota_feature_key, quota_amount, quota_period_key,
            quota_usage_event_id,
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
        db = SessionLocal()
        try:
            record = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
            if record and record.status not in _TERMINAL_TASK_STATUSES:
                record.status = "cancel_requested"
                self._merge_task_metadata(record, {"stage": "cancel_requested", "message": "正在取消任务..."})
                db.commit()
        finally:
            db.close()
        return True

    def request_cancellation_by_prefix(self, task_id_prefix: str) -> list[str]:
        """Request graceful cancellation for all running tasks with the prefix."""
        matched = [
            task_id
            for task_id in self._running_tasks
            if task_id.startswith(task_id_prefix)
        ]
        for task_id in matched:
            self.request_cancellation(task_id)
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
                BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
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

                self._finalize_failed_task_billing(task, db)

                if task.task_id in self._running_tasks:
                    self._running_tasks[task.task_id].cancel()

            db.commit()
            return len(stale_tasks)
        finally:
            db.close()

    def fail_interrupted_tasks(self) -> int:
        """应用启动时终止已失去执行者的任务，并按已有产物完成结算。"""
        db = SessionLocal()
        try:
            interrupted_tasks = db.query(BackgroundTask).filter(or_(
                BackgroundTask.status.in_(["pending", "running", "retrying", "cancel_requested"]),
                and_(
                    BackgroundTask.status == "failed",
                    BackgroundTask.error_message == "检测到重复活动任务，系统已自动终结",
                ),
            )).all()
            for task in interrupted_tasks:
                task.status = "failed"
                task.error_message = "服务重启导致任务中断，积分已按实际产物自动结算"
                task.completed_at = _now_naive()
                self._merge_task_metadata(
                    task,
                    {
                        "stage": "failed",
                        "message": task.error_message,
                        "next_retry_at": None,
                    },
                )
                self._finalize_failed_task_billing(task, db)
            db.commit()
            return len(interrupted_tasks)
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
