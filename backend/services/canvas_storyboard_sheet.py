"""画布分镜板：一张 16:9 的大图，按导演拆出的时间段分格，有几个时间段就有几格。

用途有两个：
1. 用户在生成视频之前先看这张板——每格的画面、人物站位、景别是否对，值不值得花视频的费用；
2. 提交视频时作为首张参考图，视频模型按格序展开画面。所以每一格的序号和时间段必须清楚地标在图上。

标注由程序写在图上，而不是让图片模型自己画字：图片模型画中文 / 数字常常出错，程序按固定的网格位置写，位置和内容都确定。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_PANELS = 9
SHEET_ASPECT_RATIO = "16:9"
SHEET_SIZE = "1920x1080"
# 格与格之间的白色间隔占整图宽度的比例（提示词里要求图片模型遵守，标注位置也按它计算）
GUTTER_RATIO = 0.015
REFERENCE_MODE = "storyboard_sheet"

# 格数 → (列数, 行数)：16:9 的整图里尽量让每格接近横幅构图，行数不超过列数
_LAYOUTS = {1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2), 5: (3, 2), 6: (3, 2), 7: (4, 2), 8: (4, 2), 9: (3, 3)}


def sheet_layout(count: int) -> tuple[int, int]:
    return _LAYOUTS[max(1, min(MAX_PANELS, int(count)))]


def _seconds(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _range_label(start: float | None, end: float | None) -> str:
    if start is None or end is None:
        return ""
    return f"{start:g}-{end:g}s"


def sheet_panels(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """从导演的时间轴（storyboard_json.segments）取出分格；没有时间轴返回空列表（此时不出分镜板）。

    时间段超过 9 个时，相邻的时间段按顺序均匀合并，保证一张图里每格还看得清。
    """
    storyboard = unit.get("storyboard_json") if isinstance(unit.get("storyboard_json"), dict) else {}
    raw = [s for s in storyboard.get("segments") or [] if isinstance(s, dict)]
    segments = [
        {
            "start": _seconds(s.get("start_second")),
            "end": _seconds(s.get("end_second")),
            "visual": str(s.get("visual_action") or s.get("story_task") or "").strip(),
            "camera": str(s.get("camera_direction") or "").strip(),
            "start_state": str(s.get("start_state") or "").strip(),
            "end_state": str(s.get("end_state") or "").strip(),
            "dialogue": str(s.get("dialogue_or_narration") or "").strip(),
        }
        for s in raw
    ]
    if not segments:
        return []
    if len(segments) > MAX_PANELS:
        groups = [segments[i * len(segments) // MAX_PANELS:(i + 1) * len(segments) // MAX_PANELS] for i in range(MAX_PANELS)]
        segments = [
            {
                "start": group[0]["start"], "end": group[-1]["end"],
                "visual": "；".join(g["visual"] for g in group if g["visual"]),
                "camera": group[0]["camera"], "start_state": group[0]["start_state"], "end_state": group[-1]["end_state"],
                "dialogue": "；".join(g["dialogue"] for g in group if g["dialogue"]),
            }
            for group in groups if group
        ]
    for index, segment in enumerate(segments, start=1):
        segment["index"] = index
        segment["label"] = _range_label(segment["start"], segment["end"])
    return segments


def panel_summary(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """写进节点配置的精简版（序号、起止秒数），运行时贴标注和提交视频时说明格序都只用这些。"""
    return [{"index": p["index"], "start": p["start"], "end": p["end"], "label": p["label"]} for p in panels]


def build_sheet_prompt(unit: dict[str, Any], panels: list[dict[str, Any]]) -> str:
    """分镜板的图片提示词：网格规格、逐格内容、一致性与禁止项。"""
    cols, rows = sheet_layout(len(panels))
    title = str(unit.get("title") or unit.get("unit_id") or "").strip()
    gutter = round(GUTTER_RATIO * 100, 1)
    lines = [
        f"一张 16:9 横版电影分镜板（Storyboard Sheet）单图。整张图是 {cols} 列 × {rows} 行的规整网格，共 {len(panels)} 格，"
        f"按从左到右、从上到下的顺序依次对应 {len(panels)} 个连续时间段，画面连起来就是一个完整的镜头。",
        f"版面要求：所有格子大小完全一致、横平竖直，没有外边距，格与格之间只有约 {gutter}% 整图宽度的纯白间隔，没有边框装饰；"
        "格子数量必须正好是 " + str(len(panels)) + " 格，不多不少。",
    ]
    if title:
        lines.append(f"镜头主题：{title}")
    for panel in panels:
        head = f"格{panel['index']}" + (f"（{panel['label']}）" if panel["label"] else "") + "："
        parts = [panel["visual"].rstrip("；。 ") or "该时间段的关键动作画面"]
        if panel["camera"]:
            parts.append(f"景别与机位：{panel['camera'].rstrip('；。 ')}")
        if panel["start_state"] or panel["end_state"]:
            parts.append(f"这一格定格在：{(panel['end_state'] or panel['start_state']).rstrip('；。 ')}")
        lines.append(head + "；".join(parts) + "。")
    lines += [
        "一致性：所有格子里同一个人物的脸型、发型、服装、体型、配饰完全一致；同一场景的空间布局、光线、色调完全一致；风格统一。",
        "每格都是一幅完整的、单独可看懂的电影画面，人物站位、朝向、景别与上面的描述对应，相邻格之间动作连贯。",
        "禁止：不要在图里画任何文字、数字、字幕、标签、水印、对话气泡；序号和时间段会由系统在每格左上角统一加上，"
        "所以每格左上角约 18% 宽、10% 高的区域不要放人物脸部或关键物体。",
    ]
    return "\n".join(lines)


def _cell_boxes(width: int, height: int, count: int) -> list[tuple[int, int, int, int]]:
    cols, rows = sheet_layout(count)
    gutter = GUTTER_RATIO * width
    cell_w = (width - gutter * (cols - 1)) / cols
    cell_h = (height - gutter * (rows - 1)) / rows
    boxes: list[tuple[int, int, int, int]] = []
    for index in range(count):
        row, col = divmod(index, cols)
        x0 = col * (cell_w + gutter)
        y0 = row * (cell_h + gutter)
        boxes.append((round(x0), round(y0), round(x0 + cell_w), round(y0 + cell_h)))
    return boxes


def stamp_sheet_labels(image_path: str, panels: list[dict[str, Any]]) -> bool:
    """在每格左上角写「序号 · 时间段」的小标签（深色底、白字）。写在原文件上，成功返回 True。

    没有可用的中文字体时只写数字和英文也能显示，不依赖中文；找不到任何字体才跳过。
    """
    from PIL import Image, ImageDraw

    from services.video_canvas_runtime import _label_font

    if not panels:
        return False
    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        width, height = image.size
        boxes = _cell_boxes(width, height, len(panels))
        font_size = max(18, round(height * 0.042))
        font = _label_font(font_size)
        if font is None:
            return False
        draw = ImageDraw.Draw(image, "RGBA")
        pad = max(6, round(width * 0.006))
        for panel, (x0, y0, _x1, _y1) in zip(panels, boxes):
            text = f"{panel['index']} · {panel['label']}" if panel.get("label") else f"{panel['index']}"
            text_w = draw.textlength(text, font=font)
            box = (x0 + pad, y0 + pad, x0 + pad + text_w + pad * 2, y0 + pad + font_size + pad)
            draw.rounded_rectangle(box, radius=max(4, pad), fill=(15, 15, 15, 215))
            draw.text((box[0] + pad, box[1] + pad * 0.5 - 1), text, font=font, fill=(255, 255, 255, 255))
        image.save(image_path, "PNG", optimize=True)
        return True
    except Exception:  # noqa: BLE001 - 标注失败不能让整张图作废，原图照常使用
        logger.warning("分镜板标注写入失败：%s", image_path, exc_info=True)
        return False


def video_sheet_description(panels: list[dict[str, Any]]) -> str:
    """提交视频时对分镜板的说明：共几格、格序规则、各格对应的时间段。"""
    if not panels:
        return ""
    cols, rows = sheet_layout(len(panels))
    ranges = "、".join(f"第{p['index']}格 {p['label']}" if p.get("label") else f"第{p['index']}格" for p in panels)
    return f"共 {len(panels)} 格（{cols}列×{rows}行，从左到右、从上到下），每格左上角标有序号和时间段：{ranges}"
