"""Shared service-level exceptions."""


class MissingApiKeyError(RuntimeError):
    """Raised when an upstream API key (DeepSeek / Image2) is not configured.

    Mapped to HTTP 400 by the FastAPI app so the frontend can show a friendly
    "请先在前端设置中填入 API Key" message.
    """

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(
            f"{provider} API Key is missing. Please set it in the frontend settings or backend .env."
        )


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
        if self.provider_message:
            payload["provider_message"] = self.provider_message
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.optimized_prompt:
            payload["optimized_prompt"] = self.optimized_prompt
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload
