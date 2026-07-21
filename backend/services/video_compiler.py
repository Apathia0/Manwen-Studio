"""Video compilation service.

Assembles rendered clips into a final video project using ffmpeg.
Supports clip concatenation, subtitle burn-in, and BGM overlay.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import public_error_message

logger = logging.getLogger(__name__)


def _ffmpeg_path() -> str:
    """Get ffmpeg executable path. Check PATH first, then common install locations."""
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    for p in [
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"


def _create_concat_file(clip_paths: list[str]) -> str:
    """Create a ffmpeg concat demuxer file from clip paths.

    Uses forward slashes for Windows paths (ffmpeg concat demuxer
    treats backslash as escape char). Single quotes in paths are
    escaped per the concat demuxer protocol.
    """
    lines = []
    for path in clip_paths:
        abs_path = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{abs_path}'")
    content = "\n".join(lines)
    fd, temp_path = tempfile.mkstemp(suffix=".txt", prefix="concat_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return temp_path


def _create_srt_file(subtitles: list[dict[str, Any]]) -> str | None:
    """Create a temporary SRT subtitle file from subtitle data.

    subtitle format: [{"start_ms": 0, "end_ms": 5000, "text": "Hello"}, ...]
    """
    if not subtitles:
        return None

    fd, temp_path = tempfile.mkstemp(suffix=".srt", prefix="subs_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for i, sub in enumerate(subtitles, 1):
            start_ms = int(sub.get("start_ms", 0))
            end_ms = int(sub.get("end_ms", 5000))
            text = sub.get("text", "")

            # Convert ms to SRT timestamp format: HH:MM:SS,mmm
            start_secs = start_ms / 1000
            end_secs = end_ms / 1000

            start_ts = f"{int(start_secs // 3600):02d}:{int((start_secs % 3600) // 60):02d}:{int(start_secs % 60):02d},{int((start_secs % 1) * 1000):03d}"
            end_ts = f"{int(end_secs // 3600):02d}:{int((end_secs % 3600) // 60):02d}:{int(end_secs % 60):02d},{int((end_secs % 1) * 1000):03d}"

            f.write(f"{i}\n{start_ts} --> {end_ts}\n{text}\n\n")

    return temp_path


async def compile_project(
    output_path: str,
    clips: list[dict[str, Any]],
    resolution: str = "1280x720",
    fps: int = 24,
    burn_subtitle: bool = True,
    subtitle_data: list[dict[str, Any]] | None = None,
    bgm_path: str | None = None,
) -> dict[str, Any]:
    """Compile video project from clips using ffmpeg.

    Args:
        output_path: Full path for the output video file
        clips: List of clip dicts with at least {"video_path": str, "duration_seconds": int}
        resolution: Output resolution (e.g., "1280x720")
        fps: Output frame rate
        burn_subtitle: Whether to burn subtitles into the video
        subtitle_data: List of subtitle dicts [{start_ms, end_ms, text}]
        bgm_path: Path to background music audio file

    Returns:
        Dict with compilation result info
    """
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = _ffmpeg_path()

    valid_clips = []
    for clip in clips:
        video_path = clip.get("video_path", "")
        if video_path and os.path.isfile(video_path):
            valid_clips.append(video_path)
        else:
            logger.warning("Clip video file not found, skipping: %s", video_path)

    if not valid_clips:
        logger.warning("No valid clips to compile, creating placeholder")
        with open(output_path, "w") as f:
            f.write(f"# Compiled video (no clips)\n# Resolution: {resolution}\n")
        return {
            "output_path": output_path,
            "status": "compiled",
            "duration_seconds": 0,
            "resolution": resolution,
            "fps": fps,
            "note": "No valid clips found",
        }

    temp_files: list[str] = []

    try:
        concat_file = _create_concat_file(valid_clips)
        temp_files.append(concat_file)

        temp_output = str(output_path) + ".tmp.mp4"

        cmd = [
            ffmpeg,
            "-y",  # overwrite output
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",  # stream copy (no re-encode for speed)
        ]

        filter_chains: list[str] = []

        if burn_subtitle and subtitle_data:
            srt_path = _create_srt_file(subtitle_data)
            if srt_path:
                temp_files.append(srt_path)
                srt_escaped = srt_path.replace(":", "\\:").replace("'", "'\\\\''")
                filter_chains.append(f"subtitles='{srt_escaped}'")

        if bgm_path and os.path.isfile(bgm_path):
            cmd.extend(["-i", bgm_path])
            filter_chains.append("[0:a]volume=1.0[a0];[1:a]volume=0.3[a1];[a0][a1]amix=inputs=2:duration=first")

        if not filter_chains:
            cmd.extend(["-an"])  # Remove audio (we'll add BGM later if needed)
            cmd.append(temp_output)
        else:
            vf = ",".join(filter_chains)
            cmd.extend(["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "23"])
            cmd.append(temp_output)

        logger.info("Running ffmpeg: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[-500:] if stderr else "Unknown error"
            logger.error("ffmpeg compilation failed: %s", error_msg)

            if valid_clips:
                import shutil
                shutil.copy2(valid_clips[0], output_path)
                logger.warning("Fell back to copying first clip as output")

            return {
                "output_path": output_path,
                "status": "partial",
                "duration_seconds": sum(c.get("duration_seconds", 0) for c in clips),
                "resolution": resolution,
                "fps": fps,
                "error": error_msg,
                "note": "ffmpeg compilation failed, used first clip as fallback",
            }

        if os.path.isfile(temp_output):
            if os.path.isfile(output_path):
                os.remove(output_path)
            os.rename(temp_output, output_path)

        total_duration = sum(c.get("duration_seconds", 0) for c in clips)
        file_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

        logger.info("Successfully compiled video to %s (%.1f MB)", output_path, file_size / (1024 * 1024))

        return {
            "output_path": output_path,
            "status": "compiled",
            "duration_seconds": total_duration,
            "resolution": resolution,
            "fps": fps,
            "file_size_bytes": file_size,
            "clip_count": len(valid_clips),
        }

    except FileNotFoundError:
        logger.warning("ffmpeg not found on system, using mock compilation")
        with open(output_path, "w") as f:
            f.write(f"# ffmpeg not found - mock compilation\n# Clips: {len(valid_clips)}\n")
        return {
            "output_path": output_path,
            "status": "mock",
            "duration_seconds": sum(c.get("duration_seconds", 0) for c in clips),
            "resolution": resolution,
            "fps": fps,
            "note": "ffmpeg not available, mock output created",
        }

    except Exception as e:
        logger.error("Compilation error: %s", e, exc_info=True)
        error_message = public_error_message(e, "视频合成失败，请稍后重试")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# 视频合成失败\n# 错误：{error_message}\n")
        return {
            "output_path": output_path,
            "status": "error",
            "error": error_message,
            "duration_seconds": sum(c.get("duration_seconds", 0) for c in clips),
        }

    finally:
        for temp_path in temp_files:
            try:
                if os.path.isfile(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
