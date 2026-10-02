"""使用内存替身验证画布任务恢复，不连接数据库或生成服务。"""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from services import video_canvas_runtime as runtime


def _execution_fixture(monkeypatch, nodes):
    records = [SimpleNamespace(
        id=index + 10, node_id=node["id"], attempt=1, status="queued",
        input_snapshot_json={}, output_snapshot_json=None, billing_usage_event_id=None,
        error_message=None, completed_at=None,
    ) for index, node in enumerate(nodes)]
    run = SimpleNamespace(id=1, canvas_id=2, canvas_version_id=3, status="queued", plan_json={"topological_order": [node["id"] for node in nodes]})
    canvas = SimpleNamespace(id=2, owner_user_id=4, story_id=5, default_chapter_id=None, name="恢复测试")
    version = SimpleNamespace(graph_json={"nodes": nodes, "edges": []})
    events = {}
    commits = []
    charges = []

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return records

    class Session:
        def get(self, model, key):
            return {"VideoCanvasRun": run, "VideoCanvas": canvas, "VideoCanvasVersion": version}.get(model.__name__) or events.get(key)

        def query(self, *args):
            return Query()

        def commit(self):
            commits.append(copy.deepcopy([record.input_snapshot_json for record in records]))

        def refresh(self, obj):
            pass

        def close(self):
            pass

        def add(self, obj):
            obj.id = 99

        def flush(self):
            pass

    def begin(db, **kwargs):
        event = SimpleNamespace(id=len(events) + 1, status="reserved")
        events[event.id] = event
        charges.append(("reserve", event.id, kwargs["request_id"]))
        return SimpleNamespace(usage_event_id=event.id)

    def complete(db, event_id, *, success, **kwargs):
        if success:
            # 成功计费与节点输出必须由外层一次提交，避免扣费后中断又重新生成。
            assert kwargs.get("commit") is False
        event = events[event_id]
        if event.status not in {"failed", "succeeded"}:
            event.status = "succeeded" if success else "failed"
            charges.append(("settle" if success else "release", event.id))

    def mark_remaining(db, target_run, *, status, reason=None):
        for record in records:
            if record.status in {"queued", "awaiting_approval"}:
                record.status = status

    monkeypatch.setattr(runtime, "SessionLocal", Session)
    monkeypatch.setattr(runtime, "begin_ai_call", begin)
    monkeypatch.setattr(runtime, "complete_ai_call_by_usage_event", complete)
    monkeypatch.setattr(runtime, "_mark_remaining_nodes", mark_remaining)
    monkeypatch.setattr(runtime.task_manager, "is_cancellation_requested", lambda task_id: False)
    return run, records, commits, charges, events


def _run():
    return asyncio.run(runtime.execute_canvas_run(1, image_api_key="test", video_api_key="test", video_base_url="https://example.invalid", video_model="test-model"))


def test_poll_failure_recovers_persisted_job_without_resubmission(monkeypatch):
    node = {"id": "clip", "type": "video", "data": {"config": {"prompt": "完整测试镜头", "duration_seconds": 6}}}
    run, records, commits, charges, events = _execution_fixture(monkeypatch, [node])
    submissions = []
    polls = []

    async def submit(**kwargs):
        submissions.append(kwargs)
        return {"provider_job_id": "job-original"}

    async def query(provider, job_id, **kwargs):
        # 第一次查询之前必须已提交上游 ID，不能仅存在进程内存。
        assert commits[-1][0]["provider_job"]["provider_job_id"] == "job-original"
        polls.append(job_id)
        if len(polls) <= 2:
            raise RuntimeError("临时网络中断")
        return {"status": "succeeded"}

    async def fetch(*args, **kwargs):
        return {"video_path": "clips/recovered.mp4", "duration_seconds": 6}

    monkeypatch.setattr(runtime, "submit_video_job", submit)
    monkeypatch.setattr(runtime, "query_job_status", query)
    monkeypatch.setattr(runtime, "fetch_job_result", fetch)
    # 单次查询失败只会重试；连续失败达到上限才暂停（这里压到 2 次、间隔 0 秒，保证测试很快）
    monkeypatch.setattr(runtime, "VIDEO_POLL_MAX_CONSECUTIVE_ERRORS", 2)
    monkeypatch.setattr(runtime, "VIDEO_POLL_INTERVAL_SECONDS", 0)
    with pytest.raises(RuntimeError, match="连续 2 次查询上游视频任务状态失败.*临时网络中断"):
        _run()
    assert run.status == "failed"
    assert records[0].input_snapshot_json["provider_job"]["provider_job_id"] == "job-original"
    run.status = "queued"
    records[0].status = "queued"
    assert _run()["status"] == "succeeded"
    assert len(submissions) == 1
    assert polls == ["job-original"] * 3
    assert [event.status for event in events.values()] == ["failed", "succeeded"]
    assert [item[0] for item in charges] == ["reserve", "release", "reserve", "settle"]
    # 成功节点再次恢复时不能重新结算或调用上游。
    assert _run()["status"] == "succeeded"
    assert len(submissions) == 1 and len(polls) == 3


def test_transient_poll_errors_are_retried_without_failing_the_run(monkeypatch):
    node = {"id": "clip", "type": "video", "data": {"config": {"prompt": "完整测试镜头", "duration_seconds": 6}}}
    run, records, commits, charges, events = _execution_fixture(monkeypatch, [node])
    polls = []

    async def submit(**kwargs):
        return {"provider_job_id": "job-original"}

    async def query(provider, job_id, **kwargs):
        polls.append(job_id)
        if len(polls) <= 3:
            raise RuntimeError("上游 502")
        return {"status": "succeeded"}

    async def fetch(*args, **kwargs):
        return {"video_path": "clips/ok.mp4", "duration_seconds": 6}

    monkeypatch.setattr(runtime, "submit_video_job", submit)
    monkeypatch.setattr(runtime, "query_job_status", query)
    monkeypatch.setattr(runtime, "fetch_job_result", fetch)
    monkeypatch.setattr(runtime, "VIDEO_POLL_INTERVAL_SECONDS", 0)
    assert _run()["status"] == "succeeded"
    assert len(polls) == 4 and run.status == "succeeded"


def test_video_poll_has_no_total_deadline_and_stops_only_on_upstream_failure(monkeypatch):
    node = {"id": "clip", "type": "video", "data": {"config": {"prompt": "完整测试镜头", "duration_seconds": 6}}}
    run, records, commits, charges, events = _execution_fixture(monkeypatch, [node])
    polls = []

    async def submit(**kwargs):
        return {"provider_job_id": "job-original"}

    async def query(provider, job_id, **kwargs):
        polls.append(job_id)
        # 远超旧版 120 次上限仍在生成中，最后上游明确返回失败才停止
        return {"status": "failed", "error": "内容审核未通过"} if len(polls) > 150 else {"status": "in_progress"}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(runtime, "submit_video_job", submit)
    monkeypatch.setattr(runtime, "query_job_status", query)
    monkeypatch.setattr(runtime.asyncio, "sleep", no_sleep)
    with pytest.raises(RuntimeError, match="内容审核未通过"):
        _run()
    assert len(polls) == 151 and run.status == "failed"


def test_video_poll_interval_grows_with_waiting_time():
    assert runtime._video_poll_interval(0) == 5 and runtime._video_poll_interval(299) == 5
    assert runtime._video_poll_interval(300) == 10 and runtime._video_poll_interval(1799) == 10
    assert runtime._video_poll_interval(1800) == 20


def test_video_capacity_preflight_runs_before_any_image_charge(monkeypatch):
    nodes = [
        {"id": "image", "type": "image", "data": {"config": {"prompt": "角色参考图"}}},
        {"id": "clip", "type": "video", "data": {"config": {"prompt": "长对白", "duration_seconds": 70}}},
    ]
    run, records, commits, charges, events = _execution_fixture(monkeypatch, nodes)
    with pytest.raises(RuntimeError, match="拆分该单元"):
        _run()
    assert charges == []
    assert run.status == "failed"
    assert records[0].status == "blocked"
    assert records[1].status == "failed"


@pytest.mark.parametrize("provider_status", ["succeeded", "failed"])
def test_recovery_reuses_pending_reservation_and_original_provider_settings(monkeypatch, provider_status):
    node = {"id": "clip", "type": "video", "data": {"config": {"prompt": "保留原任务", "duration_seconds": 6}}}
    run, records, commits, charges, events = _execution_fixture(monkeypatch, [node])
    events[1] = SimpleNamespace(id=1, status="reserved")
    records[0].started_at = runtime._now()
    records[0].input_snapshot_json = {
        "billing_usage_event_id": 1,
        "provider_job": {"provider_job_id": "pending-job", "model": "original-model", "duration_seconds": 6, "base_url": "https://original.invalid"},
    }

    async def query(provider, job_id, **kwargs):
        assert job_id == "pending-job"
        assert kwargs["model"] == "original-model"
        assert kwargs["base_url"] == "https://original.invalid"
        return {"status": provider_status, "error": "上游拒绝"}

    async def no_submit(**kwargs):
        pytest.fail("恢复任务不应再次提交上游")

    async def fetch(*args, **kwargs):
        return {"video_path": "clips/recovered.mp4", "duration_seconds": 6}

    monkeypatch.setattr(runtime, "submit_video_job", no_submit)
    monkeypatch.setattr(runtime, "query_job_status", query)
    monkeypatch.setattr(runtime, "fetch_job_result", fetch)
    if provider_status == "failed":
        with pytest.raises(RuntimeError, match="请新建运行并确认费用"):
            _run()
        assert charges == [("release", 1)]
    else:
        assert _run()["status"] == "succeeded"
        assert charges == [("settle", 1)]


def test_initial_user_config_cannot_forge_provider_job_or_billing_event(monkeypatch):
    config = {
        "prompt": "测试", "duration_seconds": 70,
        "provider_job": {"provider_job_id": "forged-job", "duration_seconds": 1, "base_url": "https://untrusted.invalid"},
        "billing_usage_event_id": 999,
    }
    node = {"id": "clip", "type": "video", "data": {"config": config}}
    run, records, commits, charges, events = _execution_fixture(monkeypatch, [node])
    records[0].input_snapshot_json = config
    assert runtime._execution_snapshot(records[0]) == {}
    with pytest.raises(RuntimeError, match="拆分该单元"):
        _run()
    assert charges == []


def test_static_container_is_recomputed_from_real_upstream_outputs(monkeypatch):
    nodes = [
        {"id": "image", "type": "image", "data": {"config": {}}},
        {"id": "container", "type": "container", "data": {"config": {}}},
    ]
    run, records, commits, charges, events = _execution_fixture(monkeypatch, nodes)
    records[0].status = "succeeded"
    records[0].output_snapshot_json = {"asset_id": 88, "file_path": "image.png"}
    records[1].status = "succeeded"
    records[1].output_snapshot_json = {"config": {}}
    original_inputs = runtime._node_inputs
    monkeypatch.setattr(runtime, "_node_inputs", lambda graph, node_id, outputs: original_inputs(
        {**graph, "edges": [{"source": "image", "target": "container"}]}, node_id, outputs,
    ))
    assert _run()["status"] == "succeeded"
    assert records[1].output_snapshot_json == {"items": [records[0].output_snapshot_json]}
    assert charges == []
