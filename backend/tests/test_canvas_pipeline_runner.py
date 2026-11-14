"""服务端自动编排运行器：阶段推断、失败自动重试、不可恢复即停、防止重复执行、可取消。"""

import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from services import canvas_pipeline_runner as runner
from services.canvas_pipeline_runner import PipelineStopped, next_pipeline_step


def node(identifier, kind, **config):
    return {"id": identifier, "type": kind, "data": {"config": config}}


SCREENPLAY = node("sp", "screenplay", content="场景1：宴会厅 / 夜 / 内\n顾沉：我进来就行。")


def graph(*nodes):
    return {"nodes": list(nodes), "edges": []}


# ---------------- 阶段推断 ----------------

def test_missing_screenplay_stops_with_a_clear_reason():
    with pytest.raises(PipelineStopped, match="还没有剧本"):
        next_pipeline_step(graph())
    with pytest.raises(PipelineStopped):
        next_pipeline_step(graph(node("empty", "screenplay", content="  ")))


def test_steps_follow_split_director_assets_compile_then_done():
    scene = node("sc", "scene", source_screenplay_node="sp", approved=True)
    assert next_pipeline_step(graph(SCREENPLAY)) == ("split", {"node_id": "sp"})
    assert next_pipeline_step(graph(SCREENPLAY, scene)) == ("director", {"scene_node_id": "sc"})
    planned = node("sc", "scene", source_screenplay_node="sp", director_plan={"units": []})
    assert next_pipeline_step(graph(SCREENPLAY, planned)) == ("assets", {"scene_node_id": "sc"})
    asset = node("hero", "image", asset_role="character", asset_scene_node="sc")
    assert next_pipeline_step(graph(SCREENPLAY, planned, asset)) == ("compile", {"scene_node_id": "sc"})
    shot = node("shot", "image", node_role="storyboard", source_scene_node="sc", unit_id="u-001")
    assert next_pipeline_step(graph(SCREENPLAY, planned, asset, shot)) is None


def test_stale_nodes_do_not_count_as_done():
    planned = node("sc", "scene", source_screenplay_node="sp", director_plan={"units": []})
    stale_asset = node("old", "image", asset_role="prop", asset_scene_node="sc", stale=True)
    assert next_pipeline_step(graph(SCREENPLAY, planned, stale_asset))[0] == "assets"


def test_manually_split_scene_without_source_field_belongs_to_the_only_screenplay():
    manual_scene = node("manual", "scene", approved=True)
    assert next_pipeline_step(graph(SCREENPLAY, manual_scene)) == ("director", {"scene_node_id": "manual"})


def test_manual_asset_nodes_marked_by_source_scene_node_count():
    planned = node("sc", "scene", source_screenplay_node="sp", director_plan={"units": []})
    manual_asset = node("a", "image", asset_role="scene", source_scene_node="sc", node_role="asset")
    assert next_pipeline_step(graph(SCREENPLAY, planned, manual_asset))[0] == "compile"


# ---------------- 运行循环 ----------------

class Harness:
    """用内存里的一张图模拟画布：每执行一步就把该步的结果写进图里。"""

    def __init__(self, monkeypatch, failures=None, effects=True):
        self.graph = graph(deepcopy(SCREENPLAY))
        self.calls = []
        self.failures = dict(failures or {})
        self.effects = effects
        self.metadata = {}
        self.cancel = False
        monkeypatch.setattr(runner, "_latest_graph", lambda canvas_id: (deepcopy(self.graph), 1, 7))
        monkeypatch.setattr(runner, "_execute_stage", self.execute)
        from services import task_manager as tm
        monkeypatch.setattr(tm.task_manager, "update_task_metadata", lambda task_id, **kw: self.metadata.update(kw))
        monkeypatch.setattr(tm.task_manager, "is_cancellation_requested", lambda task_id: self.cancel)

    async def execute(self, canvas_id, owner, stage, params, action_id):
        self.calls.append((stage, deepcopy(params)))
        pending = self.failures.get(stage) or []
        if pending:
            raise pending.pop(0)
        if not self.effects:
            return {"ok": True}
        nodes = self.graph["nodes"]
        if stage == "split":
            nodes.append(node("sc", "scene", source_screenplay_node="sp", approved=True))
        elif stage == "director":
            next(n for n in nodes if n["id"] == "sc")["data"]["config"]["director_plan"] = {"units": []}
            return {"ok": True, "warnings": ["镜头 u-002 的时间轴多次未通过校验，已按原文自动生成（保守分镜）"]}
        elif stage == "assets":
            nodes.append(node("hero", "image", asset_role="character", asset_scene_node="sc"))
        elif stage == "compile":
            nodes.append(node("shot", "image", node_role="storyboard", source_scene_node="sc", unit_id="u-001", prompt="顾沉走进宴会厅"))
        return {"ok": True}


def run(**kwargs):
    return asyncio.run(runner.run_canvas_pipeline(1, 7, task_id="t1", **kwargs))


def test_runs_all_remaining_stages_in_order(monkeypatch):
    harness = Harness(monkeypatch)
    result = run()
    assert result["status"] == "succeeded"
    assert [stage for stage, _ in harness.calls] == ["split", "director", "assets", "compile"]
    assert [step["status"] for step in result["steps"]] == ["succeeded"] * 4
    assert harness.metadata["stage"] == "completed"
    # 导演阶段的保守兜底会被记为"系统自动修复"
    assert any("自动生成" in fix for fix in result["auto_fixes"])


def test_recoverable_failure_is_retried_with_a_finer_grained_constraint(monkeypatch):
    harness = Harness(monkeypatch, failures={"director": [HTTPException(422, "u3时间段对白无法在分配时间内完成")]})
    result = run(user_constraints="悬疑，冷色调")
    director_calls = [params for stage, params in harness.calls if stage == "director"]
    assert len(director_calls) == 2
    # 用户自己的约束两次都传；“细分镜头”的重试提示只作为临时的 retry_hint 出现在第二次，不会混进会被存进画布设置的 user_constraints
    assert director_calls[0]["user_constraints"] == director_calls[1]["user_constraints"] == "悬疑，冷色调"
    assert "retry_hint" not in director_calls[0] and director_calls[1]["retry_hint"] == runner.RETRY_HINT
    assert any("自动调整后重试成功" in fix for fix in result["auto_fixes"])


def test_unrecoverable_failure_stops_immediately_with_the_real_reason(monkeypatch):
    harness = Harness(monkeypatch, failures={"assets": [HTTPException(402, "积分不足，请充值后继续")]})
    with pytest.raises(PipelineStopped, match="积分不足"):
        run()
    assert [stage for stage, _ in harness.calls].count("assets") == 1
    assert harness.metadata["stage"] == "failed"


def test_failure_after_all_attempts_reports_the_last_error(monkeypatch):
    errors = [HTTPException(422, "拆分结果被截断"), HTTPException(422, "拆分结果被截断")]
    harness = Harness(monkeypatch, failures={"split": errors})
    with pytest.raises(PipelineStopped, match="拆分剧本失败：拆分结果被截断"):
        run()
    assert len(harness.calls) == runner.MAX_STAGE_ATTEMPTS


def test_step_that_succeeds_without_effect_does_not_loop_forever(monkeypatch):
    harness = Harness(monkeypatch, effects=False)
    with pytest.raises(PipelineStopped, match="没有出现对应结果"):
        run()
    assert len(harness.calls) == 2


def test_cancellation_stops_before_the_next_step(monkeypatch):
    harness = Harness(monkeypatch)
    harness.cancel = True
    assert run()["status"] == "cancelled"
    assert harness.calls == []


# ---------------- 局部重做与自动质检 ----------------

def test_scene_filter_only_processes_the_requested_scene():
    a = node("a", "scene", source_screenplay_node="sp", approved=True)
    b = node("b", "scene", source_screenplay_node="sp", director_plan={"units": []})
    assert next_pipeline_step(graph(SCREENPLAY, a, b), {"b"}) == ("assets", {"scene_node_id": "b"})
    assert next_pipeline_step(graph(SCREENPLAY, a, b), {"a"}) == ("director", {"scene_node_id": "a"})
    # 局部重做不会再去拆分剧本
    assert next_pipeline_step(graph(SCREENPLAY), {"a"}) is None


def test_quality_loop_repairs_a_fixable_error_once_then_finishes(monkeypatch):
    harness = Harness(monkeypatch)
    repairs = []

    def fake_review(graph_):
        return {"error_count": 1, "checkpoints": {}}

    def fake_targets(review):
        return {} if repairs else {("sc", "assets"): ["角色 顾沉 没有角色资产"]}

    def fake_repair(canvas_id, owner, scene_id, stage):
        repairs.append((scene_id, stage))
        harness.graph["nodes"] = [n for n in harness.graph["nodes"] if n["id"] != "hero"]

    from services import canvas_quality_review as qr
    monkeypatch.setattr(qr, "review_graph", fake_review)
    monkeypatch.setattr(qr, "repair_targets", fake_targets)
    monkeypatch.setattr(runner, "_apply_repair", fake_repair)
    result = run()
    assert result["status"] == "succeeded"
    assert repairs == [("sc", "assets")]
    assert [s for s, _ in harness.calls].count("assets") == 2
    assert any("自动质检" in fix for fix in result["auto_fixes"])


def test_transient_upstream_errors_get_more_attempts_with_backoff_and_no_prompt_change(monkeypatch):
    from services.errors import UpstreamServiceError

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)
    outage = [UpstreamServiceError("导演编排服务暂时不可用", retryable=True, provider="DeepSeek", status_code=500) for _ in range(3)]
    harness = Harness(monkeypatch, failures={"director": outage})
    result = run()
    director_calls = [params for stage, params in harness.calls if stage == "director"]
    assert result["status"] == "succeeded" and len(director_calls) == 4  # 前三次上游不可用，第四次成功
    assert sleeps == [5, 15, 30]
    assert all("retry_hint" not in params for params in director_calls)  # 上游故障不是内容问题，不改提示词


def test_transient_errors_stop_after_the_limit(monkeypatch):
    from services.errors import UpstreamServiceError

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)
    outage = [UpstreamServiceError("暂时不可用", retryable=True, provider="DeepSeek", status_code=500) for _ in range(10)]
    harness = Harness(monkeypatch, failures={"split": outage})
    with pytest.raises(PipelineStopped, match="暂时不可用"):
        run()
    assert len([1 for stage, _ in harness.calls if stage == "split"]) == runner.MAX_TRANSIENT_ATTEMPTS


def test_director_reports_the_real_reason_for_billing_and_auth_failures_instead_of_temporarily_unavailable():
    from services.video_canvas_director import _director_http_error

    message, retryable, code = _director_http_error(402)
    assert "额度不足" in message and "充值" in message and retryable is False and code == "director_plan_insufficient_balance"
    for status in (401, 403):
        assert "密钥" in _director_http_error(status)[0] and _director_http_error(status)[1] is False
    assert "不存在" in _director_http_error(404)[0] and _director_http_error(404)[1] is False
    assert _director_http_error(429)[1] is True and _director_http_error(503) == ("导演编排服务暂时不可用，请稍后重试", True, "director_plan_failed")


def test_pipeline_stops_at_once_on_insufficient_balance_with_the_clear_message(monkeypatch):
    from services.errors import UpstreamServiceError
    from services.video_canvas_director import _director_http_error

    message, retryable, code = _director_http_error(402)
    failure = UpstreamServiceError(message, retryable=retryable, provider="DeepSeek", status_code=402, code=code)
    harness = Harness(monkeypatch, failures={"director": [failure]})
    with pytest.raises(PipelineStopped, match="额度不足.*充值"):
        run()
    assert len([1 for stage, _ in harness.calls if stage == "director"]) == 1  # 欠费重试没有意义，一次就停
