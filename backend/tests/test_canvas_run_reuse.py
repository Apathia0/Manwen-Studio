"""Shared canvas run reuse contract tests."""

from types import SimpleNamespace

from services.canvas_run_reuse import (
    definition_hash,
    find_reusable_outputs,
    invalidated_node_ids,
    normalize_node_ids,
    scope_node_ids,
)
from models import VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion


def _node(node_id, node_type="image", **config):
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0, "y": 0},
        "data": {"config": config},
    }


def test_scope_and_invalidation_follow_active_upstream_edges():
    graph = {
        "nodes": [_node("source", "text", content="a"), _node("image"), _node("video", "video")],
        "edges": [
            {"id": "e1", "source": "source", "target": "image"},
            {"id": "e2", "source": "image", "target": "video"},
            {"id": "disabled", "source": "source", "target": "video", "data": {"disabled": True}},
        ],
    }
    assert scope_node_ids(graph, "video") == {"source", "image", "video"}
    assert invalidated_node_ids(graph, {"source"}) == {"image", "video"}
    assert invalidated_node_ids(graph, {"video"}) == {"video"}


def test_definition_hash_ignores_only_reuse_marker_state():
    graph = {"nodes": [_node("image", prompt="same")], "edges": []}
    fingerprint = definition_hash(graph, "image")
    graph["nodes"][0]["data"]["config"].update(asset_id=8, _reused_definition_hash=fingerprint)
    assert definition_hash(graph, "image") == fingerprint
    graph["nodes"][0]["data"]["config"]["prompt"] = "changed"
    assert definition_hash(graph, "image") != fingerprint


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, run, run_node, version):
        self.run = run
        self.run_node = run_node
        self.version = version

    def query(self, model):
        if model is VideoCanvasRun:
            return _Query([self.run])
        if model is VideoCanvasRunNode:
            return _Query([self.run_node])
        return _Query([])

    def get(self, model, identifier):
        if model is VideoCanvasVersion:
            return self.version
        return None


def test_find_reusable_outputs_returns_matching_asset_snapshot_without_mutating_graph():
    graph = {"nodes": [_node("image", prompt="same")], "edges": []}
    run = SimpleNamespace(id=3, canvas_id=1, status="succeeded", canvas_version_id=4)
    run_node = SimpleNamespace(
        run_id=3,
        node_id="image",
        status="succeeded",
        attempt=1,
        output_snapshot_json={"asset_id": 42, "url": "/static/manga/42.png"},
    )
    version = SimpleNamespace(graph_json={"nodes": [_node("image", prompt="same")], "edges": []})
    result = find_reusable_outputs(graph, 1, _Db(run, run_node, version))
    assert result == {"image": {"asset_id": 42, "url": "/static/manga/42.png"}}
    assert "asset_id" not in graph["nodes"][0]["data"]["config"]


def test_normalize_node_ids_does_not_split_strings_into_characters():
    assert normalize_node_ids("image-1") == {"image-1"}
    assert normalize_node_ids(["image-1", 2, ""]) == {"image-1", "2"}
