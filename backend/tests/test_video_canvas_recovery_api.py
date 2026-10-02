"""恢复运行接口必须保留冻结快照、成功产物及已提交的上游任务。"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from models import VideoCanvasRun, VideoCanvasRunNode
from routers import video, video_canvas
from schemas import VideoCanvasRunConfirmRequest


def test_director_compilation_keeps_content_budget_before_model_validation():
    """编译不能先压缩时长，让运行前的容量门禁失去原始内容预算。"""
    compiled = video_canvas._compile_scene_items_from_director_plan(
        plan={"units": [{"unit_id": "u1", "sequence": 1, "duration_seconds": 30, "video_prompt": "完整的三十秒对白"}]},
        plan_hash="plan", scene_node_id="scene", scene_config={"model_id": 1},
        db=SimpleNamespace(get=lambda *_: SimpleNamespace(capabilities_json={"video": {"duration_options": [5, 10, 15]}})),
    )
    assert compiled[0]["duration_seconds"] == 30
    assert compiled[0]["duration_requested"] == 30
    assert compiled[0]["video_prompt"] == "完整的三十秒对白"


@pytest.mark.parametrize("dispatch_fails", [False, True])
def test_confirm_failed_run_preserves_provider_job_and_successful_nodes(monkeypatch, dispatch_fails):
    engine = create_engine("sqlite:///:memory:")
    VideoCanvasRun.__table__.create(engine)
    VideoCanvasRunNode.__table__.create(engine)
    submitted = []

    async def submit(**kwargs):
        submitted.append(kwargs)
        if dispatch_fails:
            raise RuntimeError("模拟派发失败")

    monkeypatch.setattr(video_canvas, "_require_user", lambda *_: SimpleNamespace(id=1))
    monkeypatch.setattr(video_canvas, "_require_canvas", lambda *_: SimpleNamespace(id=1, story_id=1, default_chapter_id=None))
    monkeypatch.setattr(main, "_user_image_api_key", lambda *_: "test-image")
    monkeypatch.setattr(video, "_user_video_api_key", lambda *_: ("test-video", "https://example.invalid", "test-model"))
    monkeypatch.setattr(video_canvas.task_manager, "submit_task", submit)

    with Session(engine) as db:
        run = VideoCanvasRun(canvas_id=1, canvas_version_id=7, status="failed", requested_by_user_id=1, error_message="查询超时", plan_json={"topological_order": ["image", "video"]})
        db.add(run)
        db.flush()
        done = VideoCanvasRunNode(run_id=run.id, node_id="image", node_type="image", status="succeeded", output_snapshot_json={"asset_id": 12})
        waiting = VideoCanvasRunNode(run_id=run.id, node_id="video", node_type="video", status="failed", input_snapshot_json={"provider_job": {"provider_job_id": "existing-job"}}, error_message="查询超时")
        db.add_all([done, waiting])
        db.commit()
        request = SimpleNamespace(state=SimpleNamespace())

        async def confirm():
            return await video_canvas.confirm_video_canvas_run(1, run.id, VideoCanvasRunConfirmRequest(), request, db)

        if dispatch_fails:
            with pytest.raises(RuntimeError, match="模拟派发失败"):
                asyncio.run(confirm())
        else:
            asyncio.run(confirm())
            # 再次点击不得重复派发同一运行。
            asyncio.run(confirm())

        db.refresh(waiting)
        db.refresh(run)
        assert len(submitted) == 1
        assert run.canvas_version_id == 7
        assert run.status == ("awaiting_approval" if dispatch_fails else "queued")
        assert done.status == "succeeded"
        assert done.output_snapshot_json == {"asset_id": 12}
        assert waiting.input_snapshot_json["provider_job"]["provider_job_id"] == "existing-job"
        assert waiting.status == ("awaiting_approval" if dispatch_fails else "queued")
    engine.dispose()
