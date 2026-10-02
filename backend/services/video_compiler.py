"""使用真实媒体校验、音轨保留和原子发布完成视频合片。"""

import asyncio
import json
import logging
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ffmpeg_path() -> str:
    """优先查找环境中的 ffmpeg，再检查常见安装位置。"""
    located = shutil.which("ffmpeg")
    if located:
        return located
    for candidate in [
        "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg",
        "C:\\ffmpeg\\bin\\ffmpeg.exe", "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return "ffmpeg"


def _ffprobe_path() -> str:
    """探测器优先与编码器使用同一套安装。"""
    executable = Path(_ffmpeg_path())
    sibling = executable.with_name("ffprobe.exe" if executable.suffix == ".exe" else "ffprobe")
    if sibling.is_file():
        return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


async def _run_process(command: list[str]) -> bytes:
    """命令失败时明确抛错，取消时先停止子进程再清理临时资源。"""
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("服务器缺少 ffmpeg 或 ffprobe，无法合成视频") from exc
    try:
        stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
        raise
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-800:] if stderr else "无错误详情"
        raise RuntimeError(f"视频媒体处理失败：{detail}")
    return stdout


async def _probe_media(path: str, *, require_video: bool = True) -> dict[str, Any]:
    """拒绝空文件、伪视频及没有有效时长的媒体，返回真实轨道信息。"""
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError(f"媒体文件不存在或为空：{path}")
    payload = await _run_process([
        _ffprobe_path(), "-v", "error", "-show_streams", "-show_format", "-of", "json", path,
    ])
    try:
        data = json.loads(payload)
        streams = data.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"
                      and not (s.get("disposition") or {}).get("attached_pic")), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        primary = video if require_video else audio
        if primary is None:
            raise ValueError("没有所需媒体轨道")
        if require_video and (int(video.get("width", 0)) <= 0 or int(video.get("height", 0)) <= 0):
            raise ValueError("视频尺寸无效")
        raw_duration = primary.get("duration")
        if raw_duration in (None, "", "N/A"):
            raw_duration = (data.get("format") or {}).get("duration")
        duration = float(raw_duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("媒体时长无效")
    except (ValueError, TypeError, AttributeError, StopIteration) as exc:
        raise RuntimeError(f"媒体文件不是有效的{'视频' if require_video else '音频'}：{path}") from exc
    return {
        "duration_seconds": duration, "has_audio": audio is not None, "video": video,
        "video_map": f"0:{video['index']}" if video and "index" in video else "0:v:0",
        "audio_map": f"0:{audio['index']}" if audio and "index" in audio else "0:a:0",
    }


def _create_concat_file(clip_paths: list[str]) -> str:
    """生成 UTF-8 无 BOM 拼接清单，并转义路径中的单引号。"""
    lines = []
    for path in clip_paths:
        absolute = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
        if "\n" in absolute or "\r" in absolute:
            raise ValueError("视频路径不能含换行符")
        lines.append(f"file '{absolute}'")
    fd, temp_path = tempfile.mkstemp(suffix=".txt", prefix="concat_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return temp_path


def _create_srt_file(subtitles: list[dict[str, Any]]) -> str | None:
    """生成字幕文件，拒绝无效时间范围。"""
    if not subtitles:
        return None

    def timestamp(value: int) -> str:
        hours, remainder = divmod(value, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    entries = []
    for index, subtitle in enumerate(subtitles, 1):
        start = int(subtitle.get("start_ms", 0))
        end = int(subtitle.get("end_ms", 5000))
        if start < 0 or end <= start:
            raise ValueError("字幕时间范围无效")
        entries.append(f"{index}\n{timestamp(start)} --> {timestamp(end)}\n{subtitle.get('text', '')}\n")
    fd, temp_path = tempfile.mkstemp(suffix=".srt", prefix="subs_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(entries))
    return temp_path


def _subtitle_filter(path: str) -> str:
    """对滤镜和滤镜选项两层语法分别转义，兼容 Windows 盘符。"""
    escaped = path.replace("\\", "/")
    escaped = escaped.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    escaped = "".join("\\" + char if char in "\\'[],;" else char for char in escaped)
    return f"subtitles=filename={escaped}"


async def compile_project(
    output_path: str,
    clips: list[dict[str, Any]],
    resolution: str = "1280x720",
    fps: int = 24,
    burn_subtitle: bool = True,
    subtitle_data: list[dict[str, Any]] | None = None,
    bgm_path: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """保留原声并合片；严格模式拒绝任何缺片，所有处理失败均抛出异常。"""
    match = re.fullmatch(r"(\d+)x(\d+)", resolution)
    if not match:
        raise ValueError("视频分辨率格式无效")
    width, height = (int(value) for value in match.groups())
    if min(width, height) < 2 or width % 2 or height % 2:
        raise ValueError("视频宽高必须为正偶数")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
        raise ValueError("视频帧率必须为 1 至 120 的整数")

    valid_clips = []
    for clip in clips:
        path = clip.get("video_path")
        if not path or not os.path.isfile(path):
            if strict:
                raise RuntimeError(f"视频片段缺失，无法完整合片：{path or '未提供路径'}")
            logger.warning("视频片段缺失，跳过：%s", path)
            continue
        valid_clips.append((str(path), await _probe_media(str(path))))
    if not valid_clips:
        raise RuntimeError("没有可用于拼接的视频片段")
    if bgm_path:
        await _probe_media(bgm_path, require_video=False)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total_duration = sum(info["duration_seconds"] for _, info in valid_clips)
    ffmpeg = _ffmpeg_path()
    temp_files: list[str] = []
    try:
        # 同目录临时工作区保证最终 replace 不跨文件系统，失败保留已有成片。
        with tempfile.TemporaryDirectory(prefix=".compile_", dir=str(destination.parent)) as workspace:
            normalized_paths = []
            for index, (path, info) in enumerate(valid_clips):
                normalized = str(Path(workspace) / f"clip_{index:05d}.mp4")
                duration = str(info["duration_seconds"])
                command = [ffmpeg, "-y", "-i", path]
                if not info["has_audio"]:
                    command.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
                command.extend([
                    "-map", info["video_map"], "-map", info["audio_map"] if info["has_audio"] else "1:a:0",
                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},setpts=PTS-STARTPTS",
                    "-af", "aresample=48000:async=1:first_pts=0,apad",
                    "-t", duration, "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-video_track_timescale", "90000", normalized,
                ])
                await _run_process(command)
                if not os.path.isfile(normalized) or os.path.getsize(normalized) <= 0:
                    raise RuntimeError("片段转码没有生成有效输出")
                normalized_paths.append(normalized)

            concat_file = _create_concat_file(normalized_paths)
            temp_files.append(concat_file)
            pending = str(Path(workspace) / "result.mp4")
            command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_file]
            if bgm_path:
                command.extend(["-stream_loop", "-1", "-i", bgm_path])
            command.extend(["-map", "0:v:0"])
            if bgm_path:
                command.extend([
                    "-filter_complex",
                    "[0:a:0]volume=1.0[original];[1:a:0]volume=0.3[music];"
                    "[original][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed]",
                    "-map", "[mixed]", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                ])
            else:
                command.extend(["-map", "0:a:0", "-c:a", "copy"])
            subtitle_path = _create_srt_file(subtitle_data) if burn_subtitle and subtitle_data else None
            if subtitle_path:
                temp_files.append(subtitle_path)
                command.extend([
                    "-vf", _subtitle_filter(subtitle_path),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
                ])
            else:
                command.extend(["-c:v", "copy"])
            command.extend(["-t", str(total_duration), "-movflags", "+faststart", pending])
            await _run_process(command)
            result = await _probe_media(pending)
            if not result["has_audio"]:
                raise RuntimeError("合片结果缺少音轨")
            tolerance = max(0.5, len(valid_clips) / fps + 0.1)
            if abs(result["duration_seconds"] - total_duration) > tolerance:
                raise RuntimeError("合片时长与完整片段不一致，未发布结果")
            video = result["video"]
            if int(video["width"]) != width or int(video["height"]) != height:
                raise RuntimeError("合片分辨率不符合要求，未发布结果")
            file_size = os.path.getsize(pending)
            os.replace(pending, destination)
            return {
                "output_path": output_path, "status": "compiled",
                "duration_seconds": result["duration_seconds"], "resolution": resolution,
                "fps": fps, "file_size_bytes": file_size, "clip_count": len(valid_clips),
            }
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("合片临时文件清理失败：%s", path, exc_info=True)
