"""后台任务并发名额：视频画布运行有独立名额，长时间轮询不占满全站任务。"""

import asyncio
import logging

import pytest

from services.task_manager import TaskManager


def test_per_type_pool_is_separate_from_the_shared_pool():
    manager = TaskManager(max_concurrent=2, per_type_limits={"video_canvas_run": 5, "ignored": 0})
    shared, shared_limit = manager._slot_for("chapter_writer")
    video, video_limit = manager._slot_for("video_canvas_run")
    unlimited, _ = manager._slot_for("ignored")
    assert (shared_limit, video_limit) == (2, 5)
    assert shared is not video and unlimited is shared


def test_long_video_runs_do_not_block_other_task_types(monkeypatch):
    """5 个长时间轮询的视频运行占满“共享池”时，别的任务不应被挤到后面；视频运行自己超过上限才排队。"""
    manager = TaskManager(max_concurrent=1, per_type_limits={"video_canvas_run": 3})
    order: list[str] = []

    async def scenario():
        gate = asyncio.Event()

        async def video(name, **_):
            order.append(f"start:{name}")
            await gate.wait()
            order.append(f"end:{name}")

        async def other(**_):
            order.append("start:other")
            return "done"

        monkeypatch.setattr(manager, "_create_task_record", lambda *a, **k: None)
        monkeypatch.setattr(manager, "_mark_task_running", lambda *a, **k: None)
        monkeypatch.setattr(manager, "_on_task_complete", lambda *a, **k: None)
        for index in range(3):
            await manager.submit_task(f"v{index}", "video_canvas_run", video, f"v{index}", timeout=None, max_retries=0)
        await manager.submit_task("o", "chapter_writer", other, timeout=None, max_retries=0)
        await asyncio.sleep(0.05)
        assert "start:other" in order, "视频任务占满自己的名额时，其它类型的任务仍能立即开始"
        assert sum(1 for item in order if item.startswith("start:v")) == 3
        gate.set()
        await asyncio.sleep(0.05)

    asyncio.run(scenario())


def test_waiting_for_a_slot_is_logged(monkeypatch, caplog):
    manager = TaskManager(max_concurrent=5, per_type_limits={"video_canvas_run": 1})

    async def scenario():
        gate = asyncio.Event()

        async def video(**_):
            await gate.wait()

        monkeypatch.setattr(manager, "_create_task_record", lambda *a, **k: None)
        monkeypatch.setattr(manager, "_mark_task_running", lambda *a, **k: None)
        monkeypatch.setattr(manager, "_on_task_complete", lambda *a, **k: None)
        await manager.submit_task("first", "video_canvas_run", video, timeout=None, max_retries=0)
        await asyncio.sleep(0.02)
        await manager.submit_task("second", "video_canvas_run", video, timeout=None, max_retries=0)
        await asyncio.sleep(0.02)
        gate.set()
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.INFO, logger="services.task_manager"):
        asyncio.run(scenario())
    assert any("second" in record.getMessage() and "排队" in record.getMessage() for record in caplog.records)
