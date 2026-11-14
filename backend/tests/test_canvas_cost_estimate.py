"""画布成本预估：与运行时同口径，覆盖积分模式、自带 Key 模式、复用与缺价格。"""

from types import SimpleNamespace

import pytest

from services import canvas_cost_estimate as cost


def node(identifier, kind, **config):
    return {"id": identifier, "type": kind, "data": {"label": identifier, "config": config}}


IMAGE_MODEL = SimpleNamespace(id=1, model_key="img", display_name="图片模型", capabilities_json={})
VIDEO_MODEL = SimpleNamespace(id=2, model_key="vid", display_name="视频模型", capabilities_json={"video": {"duration_options": [5, 10]}})


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(mode="platform", available="100", prices={1: ("per_image", {"points_per_image": 2}), 2: ("per_second", {"points_per_second": 1.5})})
    monkeypatch.setattr(cost, "_reusable_outputs", lambda *args: None)
    monkeypatch.setattr(cost, "resolve_credential_mode", lambda *args: state.mode)
    monkeypatch.setattr(cost, "resolve_model", lambda db, uid, modality, model_id=None, task_type=None: IMAGE_MODEL if modality == "image" else VIDEO_MODEL)

    def price(db, model_id):
        if model_id not in state.prices:
            return None
        billing_type, config = state.prices[model_id]
        return SimpleNamespace(billing_type=billing_type, price_config_json=config)

    monkeypatch.setattr(cost, "get_active_price", price)
    monkeypatch.setattr(cost.points_accounts, "ensure_account", lambda db, uid: SimpleNamespace(available_points=state.available))
    state.db = SimpleNamespace(commit=lambda: None)
    return state


def estimate(env, nodes, edges=None, targets=None):
    return cost.estimate_canvas_cost({"nodes": nodes, "edges": edges or []}, canvas_id=1, user_id=9, db=env.db, target_node_ids=targets)


def test_platform_mode_sums_image_and_video_points(env):
    nodes = [node("shot", "image", node_role="storyboard"), node("clip", "video", duration_seconds=5)]
    edges = [{"source": "shot", "target": "clip"}]
    result = estimate(env, nodes, edges)
    assert result["image_count"] == 1 and result["video_count"] == 1
    assert result["video_seconds"] == 5
    assert result["total_points"] == pytest.approx(2 + 7.5)
    assert result["available_points"] == 100 and result["sufficient"] is True


def test_target_video_includes_upstream_images_but_not_unrelated_nodes(env):
    nodes = [node("a", "image"), node("v", "video", duration_seconds=5), node("other", "image")]
    result = estimate(env, nodes, [{"source": "a", "target": "v"}], targets=["v"])
    assert {i["node_id"] for i in result["items"]} == {"a", "v"}


def test_generated_nodes_are_reused_and_free(env):
    nodes = [node("done", "image", asset_id=5), node("todo", "image")]
    result = estimate(env, nodes)
    assert result["reused_count"] == 1 and result["image_count"] == 1
    assert result["total_points"] == 2


def test_stale_nodes_are_ignored(env):
    result = estimate(env, [node("old", "image", stale=True)])
    assert result["items"] == [] and result["total_points"] == 0


def test_insufficient_points_is_reported(env):
    env.available = "1"
    assert estimate(env, [node("a", "image")])["sufficient"] is False


def test_missing_price_warns_and_blocks_sufficient(env):
    env.prices.pop(1)
    result = estimate(env, [node("a", "image")])
    assert any("未配置积分价格" in w for w in result["warnings"])
    assert result["sufficient"] is False


def test_user_key_mode_reports_counts_without_points(env):
    env.mode = "user_key"
    result = estimate(env, [node("a", "image"), node("v", "video", duration_seconds=10)])
    assert result["credential_mode"] == "user_key"
    assert result["total_points"] is None and result["sufficient"] is None
    assert result["image_count"] == 1 and result["video_seconds"] == 10


def test_video_duration_is_normalized_to_model_tiers(env):
    result = estimate(env, [node("v", "video", duration_seconds=7)])
    assert result["video_seconds"] == 10


def test_audio_reference_warns_when_model_lacks_capability(env):
    nodes = [node("voice", "audio", asset_id=1), node("clip", "video", duration_seconds=5)]
    edges = [{"source": "voice", "target": "clip", "sourceHandle": "audio", "targetHandle": "audio"}]
    warnings = estimate(env, nodes, edges)["warnings"]
    assert any("未声明音频参考能力" in w for w in warnings)


def test_audio_reference_within_declared_limit_has_no_warning(env, monkeypatch):
    capable = SimpleNamespace(id=2, model_key="vid", display_name="视频模型", capabilities_json={"video": {"duration_options": [5, 10], "limits": {"max_reference_audios": 1}}})
    monkeypatch.setattr(cost, "resolve_model", lambda db, uid, modality, model_id=None, task_type=None: IMAGE_MODEL if modality == "image" else capable)
    nodes = [node("voice", "audio", asset_id=1), node("clip", "video", duration_seconds=5)]
    edges = [{"source": "voice", "target": "clip", "sourceHandle": "audio", "targetHandle": "audio"}]
    assert not any("音频" in w for w in estimate(env, nodes, edges)["warnings"])
