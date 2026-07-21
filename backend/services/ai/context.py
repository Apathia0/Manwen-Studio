from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class AIExecutionContext:
    request_id: str
    user_id: int
    task_type: str
    credential_mode: str
    channel_id: int
    model_id: int
    model_key: str
    modality: str
    base_url: str
    api_key: str
    adapter_type: str
    price_snapshot: dict[str, Any] | None
    estimated_points: Decimal | None
    reserved_points: Decimal | None
    usage_event_id: int | None = None
