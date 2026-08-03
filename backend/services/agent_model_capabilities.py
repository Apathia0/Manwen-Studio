"""Agent 模型能力的自动学习与动态预算计算。"""

from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any

from database import SessionLocal
from models import PlatformSetting
from sqlalchemy.exc import IntegrityError


_SETTING_PREFIX = "agent.model_capability."
_UNKNOWN_CONTEXT_WINDOW = 96_000
_DEFAULT_OUTPUT_TOKENS = 4_096
_MAX_OPTIMISTIC_OUTPUT_TOKENS = 8_192


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def capability_setting_key(base_url: str, model: str) -> str:
    identity = f"{str(base_url or '').strip().rstrip('/')}\n{str(model or '').strip()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"{_SETTING_PREFIX}{digest}"


def load_model_capability(base_url: str, model: str, db=None) -> dict[str, Any]:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        row = session.query(PlatformSetting).filter_by(
            setting_key=capability_setting_key(base_url, model)
        ).first()
        payload = row.value_json if row and isinstance(row.value_json, dict) else {}
        return dict(payload)
    finally:
        if owns_session:
            session.close()


def dynamic_output_limit(capability: dict[str, Any] | None) -> int:
    capability = capability if isinstance(capability, dict) else {}
    observed_max = _positive_int(capability.get("observed_output_limit"))
    accepted_request = _positive_int(capability.get("largest_accepted_output_request"))
    if observed_max is None and accepted_request is None:
        return _DEFAULT_OUTPUT_TOKENS
    return max(1_024, min(_MAX_OPTIMISTIC_OUTPUT_TOKENS, observed_max or accepted_request or _DEFAULT_OUTPUT_TOKENS))


def dynamic_prompt_budget(
    capability: dict[str, Any] | None,
    *,
    reserved_output_tokens: int,
) -> int:
    """按已学习窗口计算输入预算；未知模型先乐观发送，超限后自动学习。"""
    capability = capability if isinstance(capability, dict) else {}
    context_window = _positive_int(capability.get("observed_context_limit")) or _UNKNOWN_CONTEXT_WINDOW
    reserve = max(1_024, int(reserved_output_tokens or _DEFAULT_OUTPUT_TOKENS))
    protocol_margin = max(4_096, int(context_window * 0.1))
    return max(8_192, context_window - reserve - protocol_margin)


def _extract_token_limit(message: str) -> int | None:
    text = str(message or "").lower().replace(",", "")
    candidates = [
        int(value)
        for value in re.findall(r"(?<![a-z0-9])([1-9][0-9]{3,8})(?![a-z0-9])", text)
    ]
    # 边界错误经常同时包含“请求值”和“允许值”，较小值通常才是服务端上限。
    return min(candidates) if candidates else None


def _extract_context_limit(message: str) -> int | None:
    text = str(message or "").lower().replace(",", "")
    for pattern in (
        r"maximum context (?:length|window)(?: is|:)?\s*([1-9][0-9]{3,8})",
        r"context (?:length|window).{0,32}?maximum(?: is|:)?\s*([1-9][0-9]{3,8})",
    ):
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return _extract_token_limit(text)


def persist_model_capability_observation(
    base_url: str,
    model: str,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    requested_output_tokens: int | None = None,
    finish_reason: str | None = None,
    context_error: str | None = None,
    output_error: str | None = None,
) -> dict[str, Any]:
    """把成功用量或上游边界错误合并到内部能力缓存。"""
    db = SessionLocal()
    try:
        key = capability_setting_key(base_url, model)
        for attempt in range(2):
            row = db.query(PlatformSetting).filter_by(setting_key=key).first()
            payload = dict(row.value_json) if row and isinstance(row.value_json, dict) else {}
            payload["model"] = str(model or "").strip()
            payload["largest_successful_prompt"] = max(
                _positive_int(payload.get("largest_successful_prompt")) or 0,
                _positive_int(prompt_tokens) or 0,
            )
            payload["largest_successful_output"] = max(
                _positive_int(payload.get("largest_successful_output")) or 0,
                _positive_int(completion_tokens) or 0,
            )
            if finish_reason and str(finish_reason).lower() != "length":
                requested = _positive_int(requested_output_tokens)
                if requested:
                    payload["largest_accepted_output_request"] = max(
                        _positive_int(payload.get("largest_accepted_output_request")) or 0,
                        requested,
                    )

            context_limit = _extract_context_limit(context_error or "")
            if context_limit:
                payload["observed_context_limit"] = context_limit
            output_limit = _extract_token_limit(output_error or "")
            if output_limit:
                payload["observed_output_limit"] = output_limit

            payload["supports_reasoning"] = True
            payload["last_verified_at"] = datetime.datetime.utcnow().isoformat()
            if row is None:
                db.add(PlatformSetting(setting_key=key, value_json=payload))
            else:
                row.value_json = payload
            try:
                db.commit()
                return payload
            except IntegrityError:
                db.rollback()
                if attempt > 0:
                    raise
        return {}
    finally:
        db.close()
