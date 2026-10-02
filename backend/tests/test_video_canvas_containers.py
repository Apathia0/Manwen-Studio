"""资产容器的版本安全、成员依赖及图协议回归测试。"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import video_canvas
from schemas import VideoCanvasContainerCreateRequest


def media_graph():
    return {
        "schema_version": 1,
        "nodes": [
            {"id": "hero", "type": "asset", "position": {"x": 600, "y": 100}, "data": {"config": {"asset_role": "character"}}},
            {"id": "scene", "type": "image", "position": {"x": 1200, "y": 300}, "data": {"config": {"asset_role": "scene"}}},
        ],
        "edges": [],
    }


def test_container_keeps_history_and_member_positions_and_dependencies():
    original = media_graph()
    before = deepcopy(original)
    graph, container_id, count = video_canvas._build_container_graph(original, ["hero", "scene", "hero"], "本场素材")

    assert original == before
    assert graph["nodes"][:2] == before["nodes"]
    assert count == 2
    assert len(graph["edges"]) == 2
    # 组框包住成员：hero(600,100) scene(1200,300)，默认 420x236，边距 顶48/左右32/底32
    container = graph["nodes"][-1]
    assert container["position"] == {"x": 568.0, "y": 52.0}
    assert container["data"]["ui"] == {"width": 1084.0, "height": 516.0}
    assert container["data"]["config"]["member_ids"] == ["hero", "scene"]
    assert all(edge["data"] == {"member": True} for edge in graph["edges"])
    validation = video_canvas._validate_graph(graph)
    assert validation["valid"], validation
    assert validation["topological_order"][-1] == container_id
    assert video_canvas._run_scope_node_ids(graph, {container_id}) == {"hero", "scene", container_id}


def test_container_can_feed_video_without_bypassing_member_execution():
    graph, container_id, _ = video_canvas._build_container_graph(media_graph(), ["hero", "scene"], "素材")
    graph["nodes"].append({"id": "render", "type": "video", "data": {"config": {"prompt": "人物进入场景"}}})
    graph["edges"].append({"id": "bundle", "source": container_id, "sourceHandle": "assets", "target": "render", "targetHandle": "image"})

    assert video_canvas._validate_graph(graph)["valid"]
    assert video_canvas._run_scope_node_ids(graph, {"render"}) == {"hero", "scene", container_id, "render"}


def test_nested_group_flatten_delivers_all_member_images_to_video():
    """嵌套组框逐级展平：外组 → 视频拿到的输入就是全部叶子成员的输出。"""
    from services.video_canvas_runtime import _node_inputs, _reference_urls

    graph = {
        "nodes": [
            {"id": "img1", "type": "image", "data": {"config": {}}},
            {"id": "img2", "type": "image", "data": {"config": {}}},
            {"id": "inner", "type": "container", "data": {"config": {}}},
            {"id": "outer", "type": "container", "data": {"config": {}}},
            {"id": "render", "type": "video", "data": {"config": {}}},
        ],
        "edges": [
            {"id": "e1", "source": "img1", "sourceHandle": "image", "target": "inner", "targetHandle": "items"},
            {"id": "e2", "source": "img2", "sourceHandle": "image", "target": "inner", "targetHandle": "items"},
            {"id": "e3", "source": "inner", "sourceHandle": "assets", "target": "outer", "targetHandle": "items"},
            {"id": "e4", "source": "outer", "sourceHandle": "assets", "target": "render", "targetHandle": "image"},
        ],
    }
    leaf_items = [{"url": "/static/manga/a.png"}, {"url": "/static/manga/b.png"}]
    outputs = {
        "img1": {"url": "/static/manga/a.png"},
        "img2": {"url": "/static/manga/b.png"},
        "inner": {"items": leaf_items},
        "outer": {"items": leaf_items},
    }

    inputs = _node_inputs(graph, "render", outputs)

    assert [value["url"] for value in inputs] == ["/static/manga/a.png", "/static/manga/b.png"]
    assert _reference_urls(inputs, SimpleNamespace(story_id=3), None) == ["/static/manga/a.png", "/static/manga/b.png"]


def test_reference_urls_excludes_video_files_from_image_references():
    """组内视频成员的输出不能混进图片参考列表。"""
    from services.video_canvas_runtime import _reference_urls

    inputs = [
        {"url": "/static/video/clip.mp4"},
        {"url": "/static/manga/frame.png"},
        {"_media_url": "https://cdn.example.com/preview.webm"},
    ]

    assert _reference_urls(inputs, SimpleNamespace(story_id=3), None) == ["/static/manga/frame.png"]


@pytest.mark.parametrize("selection", [[], ["missing"], ["text"]])
def test_container_rejects_empty_unknown_or_non_media_members(selection):
    graph = media_graph()
    graph["nodes"].append({"id": "text", "type": "text"})
    with pytest.raises(HTTPException) as exc:
        video_canvas._build_container_graph(graph, selection, "素材")
    assert exc.value.status_code == 422


def test_container_creation_rejects_stale_revision_without_writing(monkeypatch):
    monkeypatch.setattr(video_canvas, "_require_user", lambda *_: SimpleNamespace(id=1))
    monkeypatch.setattr(video_canvas, "_lock_canvas", lambda *_: SimpleNamespace(id=5, definition_revision=4))
    body = VideoCanvasContainerCreateRequest(name="素材", node_ids=["hero"], expected_definition_revision=3)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(video_canvas.create_node_container(5, body, SimpleNamespace(), SimpleNamespace()))
    assert exc.value.status_code == 409


def test_container_creation_creates_new_version_without_mutating_previous(monkeypatch):
    graph = media_graph()
    before = deepcopy(graph)
    canvas = SimpleNamespace(id=5, definition_revision=4)
    added = []
    committed = []
    db = SimpleNamespace(add=added.append, commit=lambda: committed.append(True))
    monkeypatch.setattr(video_canvas, "_require_user", lambda *_: SimpleNamespace(id=1))
    monkeypatch.setattr(video_canvas, "_lock_canvas", lambda *_: canvas)
    monkeypatch.setattr(video_canvas, "_latest_version", lambda *_: SimpleNamespace(graph_json=graph))

    result = asyncio.run(video_canvas.create_node_container(
        5, VideoCanvasContainerCreateRequest(name="素材", node_ids=["hero"], expected_definition_revision=4), SimpleNamespace(), db,
    ))

    assert graph == before
    assert canvas.definition_revision == 5
    assert added[0].version_no == 5
    assert len(added[0].graph_json["nodes"]) == 3
    assert committed == [True]
    assert result["node_count"] == 1
