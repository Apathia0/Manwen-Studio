from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from docx import Document

from services.manga_storyboard_storage import canonical_scenes_hash


START_MARKER = ":::storycanvas-manga-storyboard version=1"
END_MARKER = ":::end-storycanvas-manga-storyboard"
SUPPORTED_SUFFIXES = {".txt", ".md", ".docx"}
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_DOCX_ENTRIES = 1000
MIN_SCENES = 1
MAX_SCENES = 20
_HEADING_PATTERN = re.compile(r"(?m)^===\s*第\s*(\d+)\s*格\s*===\s*$")
_EPISODE_PATTERN = re.compile(r"(?m)^\s*第\s*([一二三四五六七八九十两\d]{1,4})\s*话\s*[：:；;]?\s*$")
_CHINESE_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def decode_uploaded_file(filename: str, data: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("仅支持 .txt、.md 或 .docx 文件")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError("导入文件不能超过 5 MB")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_DOCX_ENTRIES:
                    raise ValueError("DOCX 文件包含过多内容项")
                if sum(entry.file_size for entry in entries) > MAX_DOCX_EXPANDED_BYTES:
                    raise ValueError("DOCX 文件解压后内容过大")
            document = Document(io.BytesIO(data))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("无法读取 DOCX 文件，请确认文件未损坏") from exc
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("文本文件必须使用 UTF-8 编码") from exc


def _parse_episode_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if "十" in value:
        tens_text, ones_text = value.split("十", 1)
        tens = _CHINESE_DIGITS.get(tens_text, 1) if tens_text else 1
        ones = _CHINESE_DIGITS.get(ones_text, 0) if ones_text else 0
        return tens * 10 + ones
    return _CHINESE_DIGITS.get(value, 0)


def _parse_numbered_scenes(
    text: str,
    pattern: re.Pattern[str],
    *,
    label: str,
    number_parser,
) -> tuple[list[str], list[str], list[str]]:
    matches = list(pattern.finditer(text))
    if not matches:
        return [], [], []
    scenes: list[str] = []
    numbers: list[int] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        scene = text[match.end():end].strip()
        if not scene:
            return [], [], [f"第 {number_parser(match.group(1))} {label}脚本为空"]
        numbers.append(number_parser(match.group(1)))
        scenes.append(scene)
    warnings = []
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        warnings.append(f"{label}序号不连续，提交时将按文件出现顺序重新编号")
    return scenes, warnings, []


def _parse_heading_scenes(text: str) -> tuple[list[str], list[str], list[str]]:
    legacy = _parse_numbered_scenes(
        text,
        _HEADING_PATTERN,
        label="格",
        number_parser=int,
    )
    if legacy[0] or legacy[2]:
        return legacy
    return _parse_numbered_scenes(
        text,
        _EPISODE_PATTERN,
        label="话",
        number_parser=_parse_episode_number,
    )


def parse_import_text(text: str, *, require_markers_for_prose: bool) -> dict:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    start_count = normalized.count(START_MARKER)
    end_count = normalized.count(END_MARKER)
    warnings: list[str] = []
    if start_count == 0 and end_count == 0:
        scenes, warnings, heading_errors = _parse_heading_scenes(normalized)
        if heading_errors:
            return _build_result([], warnings, heading_errors)
        if scenes:
            return _build_result(scenes, warnings, [])
        error = (
            "请使用独占一行的“第一话”“第二话”等标题分隔每格分镜"
            if require_markers_for_prose
            else "未识别到有效分镜格式"
        )
        return _build_result([], warnings, [error])
    if start_count != 1 or end_count != 1:
        return _build_result([], warnings, ["分镜正文必须各包含一个开始标记和结束标记"])
    start = normalized.index(START_MARKER) + len(START_MARKER)
    end = normalized.index(END_MARKER)
    if end <= start:
        return _build_result([], warnings, ["分镜结束标记必须位于开始标记之后"])
    inner = normalized[start:end].strip()
    scenes, heading_warnings, heading_errors = _parse_heading_scenes(inner)
    warnings.extend(heading_warnings)
    if heading_errors:
        return _build_result([], warnings, heading_errors)
    if not scenes:
        scenes = [part.strip() for part in re.split(r"\n\s*\n+", inner) if part.strip()]
        if scenes:
            warnings.append("正文已按空行拆分为分镜格")
    return _build_result(scenes, warnings, [])


def _build_result(scenes: list[str], warnings: list[str], errors: list[str]) -> dict:
    normalized = [scene.strip() for scene in scenes if scene.strip()]
    if normalized and not MIN_SCENES <= len(normalized) <= MAX_SCENES:
        errors = [*errors, f"每章分镜数量必须为 {MIN_SCENES}-{MAX_SCENES} 格"]
    if not normalized and not errors:
        errors = ["未解析到分镜脚本"]
    return {
        "scenes": normalized,
        "warnings": warnings,
        "errors": errors,
        "canonical_hash": canonical_scenes_hash(normalized),
    }
