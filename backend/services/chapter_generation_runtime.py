from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass


CHAPTER_GENERATION_CONCURRENCY = max(
    1,
    min(5, int(os.getenv("CHAPTER_GENERATION_CONCURRENCY", "2") or "2")),
)
CHAPTER_GENERATION_SEMAPHORE = asyncio.Semaphore(CHAPTER_GENERATION_CONCURRENCY)

_CHAPTER_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}
_CHAPTER_LOCK_REFERENCES: dict[tuple[int, int], int] = {}
_CHAPTER_LOCK_REGISTRY_GUARD = asyncio.Lock()


class ChapterGenerationBusyError(RuntimeError):
    """同一章节已有生成任务时返回，避免重复调用模型。"""


@dataclass
class ChapterGenerationLease:
    """正文生成并发租约，确保全局限流并避免同章重复生成。"""

    key: tuple[int, int]
    lock: asyncio.Lock
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        self.lock.release()
        CHAPTER_GENERATION_SEMAPHORE.release()
        async with _CHAPTER_LOCK_REGISTRY_GUARD:
            references = _CHAPTER_LOCK_REFERENCES.get(self.key, 1) - 1
            if references <= 0:
                _CHAPTER_LOCK_REFERENCES.pop(self.key, None)
                if not self.lock.locked():
                    _CHAPTER_LOCKS.pop(self.key, None)
            else:
                _CHAPTER_LOCK_REFERENCES[self.key] = references


async def acquire_chapter_generation_lease(
    story_id: int,
    chapter_number: int,
    *,
    wait_if_busy: bool = True,
) -> ChapterGenerationLease:
    """获取正文生成租约；不同入口共用同一并发和同章互斥策略。"""
    key = (int(story_id), int(chapter_number))
    async with _CHAPTER_LOCK_REGISTRY_GUARD:
        lock = _CHAPTER_LOCKS.setdefault(key, asyncio.Lock())
        references = _CHAPTER_LOCK_REFERENCES.get(key, 0)
        if (lock.locked() or references > 0) and not wait_if_busy:
            raise ChapterGenerationBusyError("该章节已有正文生成任务正在运行")
        _CHAPTER_LOCK_REFERENCES[key] = references + 1
    lock_acquired = False
    try:
        await lock.acquire()
        lock_acquired = True
        # 先排同章队列再占用全局槽位，避免同章等待者挤占其他章节吞吐。
        await CHAPTER_GENERATION_SEMAPHORE.acquire()
    except BaseException:
        if lock_acquired:
            lock.release()
        async with _CHAPTER_LOCK_REGISTRY_GUARD:
            references = _CHAPTER_LOCK_REFERENCES.get(key, 1) - 1
            if references <= 0:
                _CHAPTER_LOCK_REFERENCES.pop(key, None)
                if not lock.locked():
                    _CHAPTER_LOCKS.pop(key, None)
            else:
                _CHAPTER_LOCK_REFERENCES[key] = references
        raise
    return ChapterGenerationLease(key=key, lock=lock)


@asynccontextmanager
async def chapter_generation_guard(story_id: int, chapter_number: int):
    """以异步上下文方式持有正文生成租约。"""
    lease = await acquire_chapter_generation_lease(story_id, chapter_number)
    try:
        yield lease
    finally:
        await lease.release()
