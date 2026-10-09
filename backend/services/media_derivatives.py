"""图片衍生版本（按宽度缩放的 WebP）。

画布节点只有几百像素宽，却一直加载 PNG 原图。这里为静态图片按需生成并磁盘缓存 WebP 缩略图：
- 请求形式：`/static/manga/xxx.png?w=480`，宽度只允许白名单档位，避免被滥用成任意缩放接口；
- 衍生文件放在对应静态根目录下的 `.derived/`（随用户数据卷持久化，容器更新不丢），
  原图更新（mtime 更新）后自动失效重建；
- 生成失败一律回退为原图，绝不影响图片回显。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# 允许的宽度档位：节点缩略 / 列表小图 / 预览 / 大图
ALLOWED_WIDTHS: tuple[int, ...] = (96, 240, 480, 720, 1280, 1920)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DERIVED_DIRNAME = ".derived"
WEBP_QUALITY = 82
# 单次转换的像素上限（约 1 亿像素），超过直接放弃衍生，回退原图
MAX_SOURCE_PIXELS = 100_000_000

# 独立线程池，避免挤占通用 run_blocking 线程池；并发 2 足够，转换是 CPU 密集型
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-derive")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def parse_width(raw: object) -> int | None:
    """把查询参数解析为白名单宽度；不合法返回 None（调用方回退原图）。"""
    try:
        width = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return width if width in ALLOWED_WIDTHS else None


def is_derivable(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def derived_path(source: Path, root: Path, width: int) -> Path:
    """衍生文件路径：root/.derived/<原相对路径>.w<width>.webp"""
    relative = source.resolve().relative_to(root.resolve())
    return root / DERIVED_DIRNAME / relative.parent / f"{relative.name}.w{width}.webp"


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            # 简单限制字典规模，避免长期运行后无限增长
            if len(_LOCKS) > 2048:
                _LOCKS.clear()
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _is_fresh(target: Path, source: Path) -> bool:
    try:
        return target.stat().st_mtime >= source.stat().st_mtime and target.stat().st_size > 0
    except OSError:
        return False


def _build(source: Path, target: Path, width: int) -> bool:
    from PIL import Image, ImageOps  # 延迟导入，避免影响应用启动

    with Image.open(source) as image:
        if image.width * image.height > MAX_SOURCE_PIXELS:
            return False
        image = ImageOps.exif_transpose(image)
        has_alpha = image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)
        image = image.convert("RGBA" if has_alpha else "RGB")
        if image.width > width:
            # 只缩小不放大；缩小后保持原宽高比
            height = max(1, round(image.height * width / image.width))
            image = image.resize((width, height), Image.Resampling.LANCZOS, reducing_gap=2.0)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            image.save(temp, format="WEBP", quality=WEBP_QUALITY, method=4)
            os.replace(temp, target)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
    return True


def ensure_derivative(source: Path, root: Path, width: int) -> Path | None:
    """阻塞：确保衍生文件存在并返回其路径；任何失败返回 None。"""
    try:
        if width not in ALLOWED_WIDTHS or not is_derivable(source) or not source.is_file():
            return None
        target = derived_path(source, root, width)
        if _is_fresh(target, source):
            return target
        # 同一衍生文件的并发请求只转换一次，其余等待后直接命中
        with _lock_for(str(target)):
            if _is_fresh(target, source):
                return target
            return target if _build(source, target, width) else None
    except Exception:  # noqa: BLE001 - 衍生图失败不能影响原图回显
        logger.warning("生成图片衍生版本失败：%s (w=%s)", source, width, exc_info=True)
        return None


async def get_derivative(source: Path, root: Path, width: int) -> Path | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_POOL, ensure_derivative, source, root, width)


async def prewarm(source: Path | str, roots: tuple[Path, ...], widths: tuple[int, ...] = (480,)) -> None:
    """生成完成后预热常用档位，让画布第一次回显就命中缩略图；失败只记日志。"""
    try:
        path = Path(source).resolve()
        for root in roots:
            try:
                path.relative_to(root.resolve())
            except ValueError:
                continue
            for width in widths:
                await get_derivative(path, root, width)
            return
    except Exception:  # noqa: BLE001
        logger.warning("预热图片衍生版本失败：%s", source, exc_info=True)
