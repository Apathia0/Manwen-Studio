"""视频时长档位归一化：AI 建议时长 → 上游模型实际支持档位。"""


def normalize_video_duration(
    seconds: int | float | None,
    *,
    model: str = "",
    capabilities: dict | None = None,
    default_seconds: int = 5,
) -> int:
    """把 AI 建议的视频时长归一到上游模型实际支持的值。

    规则（按顺序生效）：
    1. seconds 为空/非法 → 返回 default_seconds；
    2. 字符串能转数字则转换，不能转则用 default_seconds；
    3. clamp 到 [2, 60]；
    4. capabilities 中若配置了该模型支持的时长档位（key：duration_options，
       允许直接放在 capabilities 顶层或其子 dict wire 下），就近归一到档位，
       距离相等时取更小的档位；
    5. 无档位配置时的兜底：Seedance 1.x（模型名含 seedance 且含 1-0/1.0/1-5/1.5）
       最大 12 秒，超出归到 12；其他模型直接取 clamp 后的整数值。

    纯函数，无 IO。
    """
    # ── 1/2. 空值与非法输入 → default ──
    value = seconds
    if isinstance(value, str):
        text = value.strip()
        try:
            value = float(text) if text else None
        except ValueError:
            value = None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default_seconds

    # ── 3. clamp 到全局安全区间 ──
    clamped = int(round(float(value)))
    clamped = max(2, min(60, clamped))

    # ── 4. 档位归一（防御式取值：顶层或 wire 子 dict）──
    options = _duration_options(capabilities)
    if options:
        return min(options, key=lambda opt: (abs(opt - clamped), opt))

    # ── 5. 无档位配置的兜底：Seedance 1.x 上限 12 秒 ──
    model_lower = str(model or "").lower()
    if "seedance" in model_lower and any(
        version in model_lower for version in ("1-0", "1.0", "1-5", "1.5")
    ):
        if clamped > 12:
            return 12
    return clamped


def _duration_options(capabilities: dict | None) -> list[int]:
    """从 capabilities dict 防御式取出 duration_options 档位列表。

    允许放在顶层（capabilities["duration_options"]）或子 dict
    capabilities["wire"]["duration_options"] 下；只接受非空的全正整数列表。
    """
    if not isinstance(capabilities, dict):
        return []
    raw: object = capabilities.get("duration_options")
    if raw is None:
        wire = capabilities.get("wire")
        if isinstance(wire, dict):
            raw = wire.get("duration_options")
    if not isinstance(raw, (list, tuple)) or not raw:
        return []
    options: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return []
        opt = int(item)
        if opt <= 0:
            return []
        options.append(opt)
    return sorted(set(options))
