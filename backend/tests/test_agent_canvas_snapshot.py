"""画布 Agent 浏览器实时快照读取回归测试。"""

import asyncio
from types import SimpleNamespace

import main  # noqa: F401 - 确保 Agent 路由绑定主模块依赖
from routers.agent_router import _sanitize_canvas_graph_snapshot
from schemas import AgentChatIn
from services import agent_service


def test_agent_chat_schema_keeps_canvas_graph_snapshot():
    graph = {"nodes": [{"id": "n1", "type": "image"}], "edges": []}
    body = AgentChatIn(
        conversation_id=1,
        message="读取当前图",
        workflow_type="video_canvas",
        workflow_id=5,
        canvas_graph=graph,
    )
    assert body.canvas_graph == graph


def test_canvas_graph_snapshot_sanitizer_falls_back_for_invalid_payloads():
    valid = {"nodes": [{"id": "n1", "type": "image"}], "edges": []}
    assert _sanitize_canvas_graph_snapshot(valid) == valid
    assert _sanitize_canvas_graph_snapshot({"nodes": "bad", "edges": []}) is None
    assert _sanitize_canvas_graph_snapshot({"nodes": [{"type": "image"}], "edges": []}) is None
    assert _sanitize_canvas_graph_snapshot({"nodes": [{"id": str(i), "type": "image"} for i in range(2001)], "edges": []}) is None


class _Query:
    def __init__(self, graph):
        self.graph = graph

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return SimpleNamespace(graph_json=self.graph)


class _Db:
    def __init__(self, canvas, graph):
        self.canvas = canvas
        self.graph = graph

    def get(self, _model, _id):
        return self.canvas

    def query(self, _model):
        return _Query(self.graph)

    def close(self):
        return None


def _canvas_context(snapshot=None):
    return agent_service.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=agent_service.PendingChangesTracker(),
        workflow_type="video_canvas",
        workflow_id=5,
        canvas_graph_snapshot=snapshot,
    )


def test_get_canvas_graph_prefers_browser_snapshot(monkeypatch):
    canvas = SimpleNamespace(id=5, story_id=1, name="测试画布", definition_revision=7)
    database_graph = {"nodes": [{"id": "db-node", "type": "text"}], "edges": []}
    browser_graph = {"nodes": [{"id": "live-node", "type": "image"}], "edges": []}
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: _Db(canvas, database_graph))
    token = agent_service._AGENT_RUN_CONTEXT.set(_canvas_context(browser_graph))
    try:
        result = asyncio.run(agent_service.get_canvas_graph(5))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)
    assert result["graph_source"] == "browser"
    assert result["graph"] == browser_graph
    assert result["definition_revision"] == 7


def test_get_canvas_graph_falls_back_to_database(monkeypatch):
    canvas = SimpleNamespace(id=5, story_id=1, name="测试画布", definition_revision=7)
    database_graph = {"nodes": [{"id": "db-node", "type": "text"}], "edges": []}
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: _Db(canvas, database_graph))
    token = agent_service._AGENT_RUN_CONTEXT.set(_canvas_context())
    try:
        result = asyncio.run(agent_service.get_canvas_graph(5))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)
    assert result["graph_source"] == "database"
    assert result["graph"] == database_graph
