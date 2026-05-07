from __future__ import annotations


REPLACEMENTS = {
    "鲜血淋漓": "激烈冲突后的狼狈状态",
    "血肉横飞": "剧烈冲击后的混乱场面",
    "开膛": "强烈对抗",
    "断肢": "受伤倒地",
    "尸体": "失去意识的人影",
    "爆头": "强力冲击",
    "枪口": "压迫感道具",
    "手枪": "金属道具",
    "步枪": "长柄道具",
    "刀尖": "锋利道具",
    "匕首": "小型锋利道具",
    "砍杀": "激烈打斗",
    "刺穿": "正面冲突",
    "勒脖": "肢体控制",
    "自杀": "情绪崩溃",
    "裸体": "衣着凌乱",
    "赤裸": "衣着简化",
    "性侵": "危险逼近",
    "强奸": "极端威胁",
    "虐杀": "危险追逐",
}

SAFE_SUFFIX = "画面强调人物表情、气氛、镜头调度与戏剧张力，避免血腥、裸露、极端暴力和违规暗示。"


def sanitize_scene_text(text: str) -> tuple[str, bool]:
    sanitized = (text or "").strip()
    changed = False
    for src, dst in REPLACEMENTS.items():
        if src in sanitized:
            sanitized = sanitized.replace(src, dst)
            changed = True
    if changed and SAFE_SUFFIX not in sanitized:
        sanitized = f"{sanitized.rstrip('。.!！？ ')}。{SAFE_SUFFIX}"
    return sanitized, changed


def sanitize_scene_list(scenes: list[str]) -> tuple[list[str], list[int]]:
    sanitized_scenes: list[str] = []
    sanitized_indices: list[int] = []
    for idx, scene in enumerate(scenes):
        sanitized, changed = sanitize_scene_text(scene)
        sanitized_scenes.append(sanitized)
        if changed:
            sanitized_indices.append(idx)
    return sanitized_scenes, sanitized_indices
