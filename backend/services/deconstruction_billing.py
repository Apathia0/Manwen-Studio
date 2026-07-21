"""拆书后台任务的积分预留结算辅助。"""

import datetime

from database import SessionLocal
from models import BackgroundTask
from services.ai.resolver import complete_ai_call_by_usage_event, refund_ai_call
from services.deepseek import consume_usage_accumulator


def settle_deconstruction_usage(usage_event_id: int | None) -> None:
    """按当前后台任务累计的 DeepSeek token 结算拆书预留。"""
    if not usage_event_id:
        return

    db = SessionLocal()
    try:
        usage = consume_usage_accumulator()
        has_provider_usage = bool(usage["input_tokens"] or usage["output_tokens"])
        complete_ai_call_by_usage_event(
            db,
            usage_event_id,
            success=True,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            usage_source="provider" if has_provider_usage else "estimated",
        )
    finally:
        db.close()


def refund_deconstruction_task(db, task_id: str | None, *, error_code: str) -> None:
    """按后台任务绑定的原始用量事件幂等释放拆书预留。"""
    if not task_id:
        return
    task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
    if not task:
        return
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    usage_event_id = int(metadata.get("billing_usage_event_id") or 0)
    if usage_event_id:
        refund_ai_call(db, usage_event_id, error_code=error_code, commit=False)
    task.status = "failed"
    task.error_message = error_code
    task.completed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    task.metadata_json = {
        **metadata,
        "stage": "failed",
        "message": error_code,
        "last_error": error_code,
        "next_retry_at": None,
    }
