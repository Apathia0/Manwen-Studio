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

    # 模型只声明了连续区间（limits.duration_seconds.min / max，如 4 到 15 秒）：区间内任意整数秒都可用，超出才收到边界
    low, high = _duration_range(capabilities)
    if low is not None or high is not None:
        if low is not None:
            clamped = max(clamped, low)
        if high is not None:
            clamped = min(clamped, high)
        return clamped

    # ── 5. 无档位配置的兜底：Seedance 1.x 上限 12 秒 ──
    model_lower = str(model or "").lower()
    if "seedance" in model_lower and any(
        version in model_lower for version in ("1-0", "1.0", "1-5", "1.5")
    ):
        if clamped > 12:
            return 12
    return clamped


def _duration_range(capabilities: dict | None) -> tuple[int | None, int | None]:
    """读取模型声明的连续时长区间 limits.duration_seconds.min / max；没有声明返回 (None, None)。"""
    limits = capabilities.get("limits") if isinstance(capabilities, dict) else None
    spec = limits.get("duration_seconds") if isinstance(limits, dict) else None
    if not isinstance(spec, dict):
        return None, None

    def positive(value: object) -> int | None:
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None

    return positive(spec.get("min")), positive(spec.get("max"))


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
    if raw is None:
        # 兼容后台“参数配置”里的写法：limits.duration_seconds.allowed 列出可选档位
        limits = capabilities.get("limits")
        spec = limits.get("duration_seconds") if isinstance(limits, dict) else None
        raw = spec.get("allowed") if isinstance(spec, dict) else None
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


# ── 作品总时长预算 ─────────────────────────────────────────
# 用本地真实画布校准：剧本去空白后的字数 ÷ 最终视频总秒数 ≈ 5.6 字/秒（节拍最少秒数口径约 6 字/秒）。
SCREENPLAY_CHARS_PER_SECOND = 5.6
# 剧本估算时长超过目标的该倍数即视为明显超长（导演阶段只能保证不压缩对白，无法替用户删剧情）。
SCREENPLAY_OVERRUN_RATIO = 1.1

# 用户给的时长只是参考：故事讲完整优先，实际可在参考值的 2 倍内浮动，但不超过短视频的合理上限 3 分钟
FLEX_DURATION_RATIO = 2.0
SHORT_VIDEO_MAX_SECONDS = 180


def target_duration_ceiling(target_seconds: int) -> int:
    """参考时长对应的“合理上限”（秒）：max(参考+30, 参考×2)，且不超过 3 分钟；参考值本身已超过 3 分钟时以参考值为准。"""
    flexible = max(target_seconds + 30, target_seconds * FLEX_DURATION_RATIO)
    return int(max(target_seconds, min(flexible, SHORT_VIDEO_MAX_SECONDS)))


def parse_target_duration_seconds(text: str | None) -> int | None:
    """从用户约束里解析目标总时长（秒）。

    只认“时长约60秒 / 总时长1分钟 / 60秒短剧”这类表达；“开场3秒内”“每10到15秒一次反转”这类节奏要求不算。
    """
    import re

    raw = str(text or "")
    if not raw:
        return None
    patterns = (
        r"(?:总|全片|成片|片)?时长[^\d\n]{0,6}(\d+(?:\.\d+)?)\s*(分钟|分|秒钟|秒|s)",
        r"(\d+(?:\.\d+)?)\s*(分钟|秒钟|秒)\s*(?:左右)?的?\s*(?:短剧|漫剧|短片|短视频|视频|成片|动画)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        value = float(match.group(1))
        seconds = value * 60 if match.group(2) in {"分钟", "分"} else value
        if 10 <= seconds <= 3600:
            return int(round(seconds))
    return None


def estimate_screenplay_seconds(text: str | None) -> float:
    """按字数估算剧本拍成视频后的总时长（秒）。"""
    import re

    chars = len(re.sub(r"\s", "", str(text or "")))
    return chars / SCREENPLAY_CHARS_PER_SECOND


def screenplay_char_budget(target_seconds: int) -> int:
    """目标时长对应的剧本字数预算（含场景标题）。"""
    return int(target_seconds * SCREENPLAY_CHARS_PER_SECOND)
