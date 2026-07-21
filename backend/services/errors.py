"""Shared service-level exceptions."""

import re


_PUBLIC_ERROR_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b402\b|payment required|insufficient (balance|credits?)", re.I), "上游 AI 服务余额不足，请充值或更换可用渠道后重试"),
    (re.compile(r"\b401\b|unauthorized|invalid api[ _-]?key|authentication failed", re.I), "身份验证失败，请检查 API Key 或重新登录"),
    (re.compile(r"\b403\b|forbidden|permission denied|access denied", re.I), "当前账号没有执行此操作的权限"),
    (re.compile(r"\b404\b|not found", re.I), "请求的资源不存在或已被删除"),
    (re.compile(r"\b408\b|timed? out|timeout", re.I), "任务执行超时，请稍后重试"),
    (re.compile(r"\b409\b|conflict|already running|duplicate", re.I), "已有相同任务正在执行或任务状态冲突，请稍后刷新"),
    (re.compile(r"\b413\b|payload too large|request entity too large", re.I), "提交内容过大，请缩短内容或减少文件大小"),
    (re.compile(r"\b422\b|validation error|unprocessable entity", re.I), "提交参数不正确，请检查输入内容"),
    (re.compile(r"\b429\b|too many requests|rate limit", re.I), "请求过于频繁，请稍后重试"),
    (re.compile(r"\b500\b|internal server error", re.I), "服务器处理失败，请稍后重试"),
    (re.compile(r"\b502\b|bad gateway", re.I), "上游 AI 服务暂时不可用，请稍后重试"),
    (re.compile(r"\b503\b|service unavailable|overloaded", re.I), "服务暂时不可用或繁忙，请稍后重试"),
    (re.compile(r"\b504\b|gateway timeout", re.I), "上游服务响应超时，请稍后重试"),
    (re.compile(r"failed to fetch|network error|connection (refused|reset|error)", re.I), "网络连接失败，请检查网络后重试"),
)


def public_error_message(error: object, fallback: str = "任务执行失败，请稍后重试") -> str:
    """将内部或上游异常转换为安全、可操作的中文提示。"""
    user_message = str(getattr(error, "user_message", "") or "").strip()
    if user_message:
        return user_message
    text = str(error or "").strip()
    if not text:
        return fallback
    for pattern, message in _PUBLIC_ERROR_RULES:
        if pattern.search(text):
            return message
    if re.search(r"[\u4e00-\u9fff]", text):
        prefix, separator, suffix = text.partition(":")
        if separator and re.search(r"[\u4e00-\u9fff]", prefix) and suffix and not re.search(r"[\u4e00-\u9fff]", suffix):
            return f"{prefix.strip()}，请稍后重试"
        return text[:300] + ("..." if len(text) > 300 else "")
    return fallback


def sanitize_public_error_detail(detail: object) -> object:
    """递归清洗结构化错误，并移除仅供服务端诊断的敏感字段。"""
    if isinstance(detail, list):
        return [sanitize_public_error_detail(item) for item in detail]
    if not isinstance(detail, dict):
        return detail

    sensitive_keys = {
        "provider_message",
        "provider_response",
        "traceback",
        "stack",
        "stack_trace",
        "internal_url",
    }
    message_keys = {"detail", "error", "error_message", "message", "user_message"}
    result: dict[str, object] = {}
    for key, value in detail.items():
        if key in sensitive_keys:
            continue
        if key in message_keys and isinstance(value, str):
            result[key] = public_error_message(value, "请求处理失败，请稍后重试")
        else:
            result[key] = sanitize_public_error_detail(value)
    return result


class MissingApiKeyError(RuntimeError):
    """Raised when an upstream API key (DeepSeek / Image2) is not configured.

    Mapped to HTTP 400 by the FastAPI app so the frontend can show a friendly
    "请先在前端设置中填入 API Key" message.
    """

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(
            f"{provider} API Key 缺失，请在前端设置或后端 .env 中配置"
        )


class UpstreamServiceError(RuntimeError):
    """Structured upstream service failure used by background retries."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        provider: str = "",
        status_code: int | None = None,
    ):
        self.retryable = retryable
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class MangaImageGenerationError(RuntimeError):
    """Structured upstream image-generation failure."""

    def __init__(
        self,
        *,
        code: str,
        user_message: str,
        retryable: bool,
        provider_message: str = "",
        status_code: int | None = None,
        optimized_prompt: str | None = None,
        suggestion: str | None = None,
        should_sanitize: bool = False,
    ):
        self.code = code
        self.user_message = user_message
        self.retryable = retryable
        self.provider_message = provider_message
        self.status_code = status_code
        self.optimized_prompt = optimized_prompt
        self.suggestion = suggestion
        self.should_sanitize = should_sanitize
        super().__init__(user_message)

    def to_payload(self) -> dict:
        payload = {
            "error": self.user_message,
            "code": self.code,
            "retryable": self.retryable,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.optimized_prompt:
            payload["optimized_prompt"] = self.optimized_prompt
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload
