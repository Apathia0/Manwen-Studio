from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def chapter_dir(backend_dir: Path, chapter_id: int) -> Path:
    return backend_dir / "manga_outputs" / f"chapter_{chapter_id}"


def scenes_path(backend_dir: Path, chapter_id: int) -> Path:
    return chapter_dir(backend_dir, chapter_id) / "scenes.txt"


def parse_scenes_text(raw: str) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"(?m)^=== .*? ===\r?\n", raw) if part.strip()]


def render_scenes_text(scenes: list[str]) -> str:
    return "".join(
        f"=== 第{index}格 ===\n{scene.strip()}\n\n"
        for index, scene in enumerate(scenes, start=1)
    )


def content_revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def canonical_scenes_hash(scenes: list[str]) -> str:
    normalized = [scene.strip() for scene in scenes]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@contextmanager
def scenes_file_lock(backend_dir: Path, chapter_id: int) -> Iterator[None]:
    """跨进程串行化同一章节的分镜文件写入。"""
    target_dir = chapter_dir(backend_dir, chapter_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    lock_path = target_dir / ".scenes.lock"
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, content: str) -> None:
    """在目标目录内落盘并原子替换，避免读取到半写文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_scenes_text_atomic(backend_dir: Path, chapter_id: int, content: str) -> None:
    atomic_write_text(scenes_path(backend_dir, chapter_id), content)
