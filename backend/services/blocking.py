"""Shared executor for blocking file, image, and OSS work."""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def _worker_count() -> int:
    raw = os.getenv("STORYCANVAS_BLOCKING_WORKERS", "4").strip()
    try:
        return max(1, min(16, int(raw)))
    except ValueError:
        return 4


_EXECUTOR = ThreadPoolExecutor(
    max_workers=_worker_count(),
    thread_name_prefix="storycanvas-blocking",
)


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a blocking callable in the shared small thread pool."""
    loop = asyncio.get_running_loop()
    call = partial(func, *args, **kwargs)
    return await loop.run_in_executor(_EXECUTOR, call)


def shutdown_blocking_executor() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=True)
