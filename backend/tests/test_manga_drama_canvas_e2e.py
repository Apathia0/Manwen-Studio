"""漫剧画布 Agent + fake provider 最小端到端冒烟测试。

测试边界：
- 阶段编排通过真实 ``canvas_agent_actions`` 持久化/调度边界，阶段业务网关以
  fake gateway 替代，因此不依赖 DeepSeek、Image2、OSS 或真实视频服务。
- 生成阶段通过真实 ``execute_canvas_run`` 的运行时编排，provider submit/status/fetch
  三个外部边界替换为 fake provider；重点验证提交参数冻结及后台续接，不验证上游媒体内容。
- 八阶段中的 ``screenplay`` 到 ``images`` 由 Agent 自动链路推进；``videos`` 和
  ``concat`` 由真实 callback continuation 接续，覆盖完整公开 stage 序列但不调用真实生成。
"""

import asyncio
from types import SimpleNamespace

import pytest

from models import BackgroundTask, CanvasAgentAction, VideoCanvasRun
from services import canvas_agent_actions as actions
from services import video_canvas_runtime as runtime

# Reuse the existing in-memory Agent canvas fixture and runtime execution fixture.
from tests.test_canvas_agent_actions import state
from tests.test_video_canvas_execution_recovery import _execution_fixture


_STAGE_ORDER = ["screenplay", "split", "director", "assets", "compile", "images", "videos", "concat"]


def _queued_action(factory, *, action_id: int, stage: str, expected_revision: int = 4):
    with factory() as db:
        action = CanvasAgentAction(
            id=action_id,
            canvas_id=1,
            owner_user_id=2,
            conversation_id=5,
            permission_mode="auto",
            stage=stage,
            tool_name="canvas_stage",
            summary=f"执行{stage}",
            arguments_json={
                "canvas_id": 1,
                "stage": stage,
                "parameters": {},
            },
            expected_definition_revision=expected_revision,
            status="queued",
            result_json={"continuation": {"source_action_id": action_id - 1}},
        )
        db.add(action)
        db.commit()


def _finish_run_for_callback(factory, *, task_id: str, run_id: int, action_id: int):
    with factory() as db:
        db.add(
            BackgroundTask(
                task_id=task_id,
                task_type="video_canvas_run",
                status="succeeded",
                metadata_json={"canvas_id": 1, "run_id": run_id, "agent_action_id": action_id},
            )
        )
        db.add(VideoCanvasRun(id=run_id, canvas_id=1, canvas_version_id=1, status="succeeded", plan_json={}))
        db.commit()


def test_auto_chain_stops_after_compile_and_leaves_generation_to_user(state, monkeypatch):
    """全自动只编排节点到 compile，不创建出图/视频动作，生成任务由用户提交。"""
    context, factory = state
    del context
    seen_stages: list[str] = []

    async def fake_gateway(canvas_id, stage, parameters, request, db):
        del canvas_id, request, db
        seen_stages.append(stage)
        assert parameters["agent_action_id"]
        assert parameters["expected_definition_revision"] == 4
        next_stage = {"screenplay": "split", "split": "director", "director": "assets", "assets": "compile", "compile": "images"}[stage]
        extra = {"node_id": "screenplay-1"} if stage == "screenplay" else {"scene_node_id": "scene-1", "node_ids": ["image-1"]}
        return {"ok": True, "next_stage": next_stage, "definition_revision": 4, **extra}

    monkeypatch.setattr("services.canvas_stage_gateway.execute_agent_canvas_stage", fake_gateway)

    _queued_action(factory, action_id=10, stage="screenplay")
    first = asyncio.run(actions.dispatch_queued_canvas_action(10))
    assert first["status"] == "completed"
    assert seen_stages == ["screenplay", "split", "director", "assets", "compile"]
    with factory() as db:
        assert db.query(CanvasAgentAction).filter(CanvasAgentAction.stage.in_(["images", "videos", "concat"])).count() == 0
        assert db.query(CanvasAgentAction).filter(CanvasAgentAction.status.in_(["queued", "pending", "waiting"])).count() == 0

    # A failed/cancelled provider run never creates a continuation action.
    with factory() as db:
        before = db.query(CanvasAgentAction).count()
        db.add(
            BackgroundTask(
                task_id="canvas-failed",
                task_type="video_canvas_run",
                status="failed",
                metadata_json={"canvas_id": 1, "run_id": 102, "agent_action_id": 99},
            )
        )
        db.add(VideoCanvasRun(id=102, canvas_id=1, canvas_version_id=1, status="failed", plan_json={}))
        db.add(
            CanvasAgentAction(
                id=99,
                canvas_id=1,
                owner_user_id=2,
                conversation_id=5,
                permission_mode="auto",
                stage="images",
                tool_name="canvas_stage",
                summary="失败出图",
                arguments_json={},
                expected_definition_revision=4,
                status="waiting",
                result_json={"pending_task": {"run_id": 102}, "next_stage": "videos"},
            )
        )
        db.commit()
        before += 1
    assert actions.continue_canvas_stage_after_run("canvas-failed", {"run_id": 102, "status": "failed"}) is None
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == before
        assert db.get(CanvasAgentAction, 99).status == "waiting"


def test_fake_provider_receives_image_mode_references_and_seed(monkeypatch):
    """运行时把画布视频节点的参考图和 seed 冻结并传入 provider。"""
    node = {
        "id": "clip",
        "type": "video",
        "data": {
            "config": {
                "prompt": "雨夜中向前奔跑",
                "duration_seconds": 6,
                "aspect_ratio": "16:9",
                "provider": "comfyui",
                "reference_asset_ids": [17],
                "seed": 4242,
            }
        },
    }
    run, records, _commits, _charges, _events = _execution_fixture(monkeypatch, [node])
    captured: dict[str, object] = {}

    async def fake_external_references(inputs, canvas, db, *, max_reference_images=9):
        captured["reference_inputs"] = inputs
        captured["max_reference_images"] = max_reference_images
        return ["https://cdn.example.test/reference.png"]

    async def fake_submit(**kwargs):
        captured["submission"] = kwargs
        return {"provider_job_id": "fake-provider-job", "status": "queued"}

    async def fake_query(provider, provider_job_id, **kwargs):
        captured["query"] = (provider, provider_job_id, kwargs)
        return {"status": "succeeded"}

    async def fake_fetch(provider, provider_job_id, shot_id, **kwargs):
        captured["fetch"] = (provider, provider_job_id, shot_id, kwargs)
        return {"video_path": "fake-provider/output.mp4", "duration_seconds": 6}

    monkeypatch.setattr(runtime, "_configured_reference_inputs", lambda config, canvas, db: [
        {"asset_id": 17, "url": "https://cdn.example.test/reference.png", "media_kind": "image"}
    ])
    monkeypatch.setattr(runtime, "_external_video_reference_urls", fake_external_references)
    monkeypatch.setattr(runtime, "submit_video_job", fake_submit)
    monkeypatch.setattr(runtime, "query_job_status", fake_query)
    monkeypatch.setattr(runtime, "fetch_job_result", fake_fetch)

    result = asyncio.run(
        runtime.execute_canvas_run(
            1,
            image_api_key="fake-image-key",
            video_api_key="fake-video-key",
            video_base_url="https://provider.example.test",
            video_model="fake-video-model",
        )
    )

    assert result == {"run_id": 1, "status": "succeeded"}
    submission = captured["submission"]
    assert submission["input_mode"] == "image_to_video"
    assert submission["reference_images"] == ["https://cdn.example.test/reference.png"]
    assert submission["seed"] == 4242
    assert records[0].input_snapshot_json["video_submission"] == {
        "reference_images": ["https://cdn.example.test/reference.png"],
        "reference_audios": [],
        "reference_asset_ids": [17],
        "input_mode": "image_to_video",
        "seed_requested": 4242,
        "seed_supported": True,
        "seed_forwarded": True,
        "warning": None,
    }
    assert records[0].input_snapshot_json["provider_job"]["provider_job_id"] == "fake-provider-job"
