"""Video compilation service.

Assembles rendered clips into a final video project.
Uses ffmpeg for actual compilation.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def compile_project(
    output_path: str,
    clips: list[dict[str, Any]],
    resolution: str = "1280x720",
    fps: int = 24,
    burn_subtitle: bool = True,
    subtitle_data: list[dict[str, Any]] | None = None,
    bgm_path: str | None = None,
) -> dict[str, Any]:
    """Compile video project from clips.

    In production, this uses ffmpeg to concatenate video clips.
    Currently a mock implementation.
    """
    # TODO: Implement actual ffmpeg compilation
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create a placeholder file
    with open(output_path, 'w') as f:
        f.write(f"# Mock compiled video\n# Clips: {len(clips)}\n# Resolution: {resolution}\n")

    logger.info("Mock compiled video project to %s", output_path)

    return {
        "output_path": output_path,
        "status": "compiled",
        "duration_seconds": sum(c.get("duration_seconds", 0) for c in clips),
        "resolution": resolution,
        "fps": fps,
    }
