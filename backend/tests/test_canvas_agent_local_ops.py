"""Agent 本地画布操作不写数据库的回归测试。"""
import asyncio
from types import SimpleNamespace

from services import agent_service


def test_apply_canvas_ops_local_returns_graph_without_version_write(monkeypatch):
    graph = {"schema_version": 1, "nodes": [{"id": "text-1", "type": "text", "data": {"label": "旧", "config": {}}}], "edges": []}
    canvas = SimpleNamespace(id=5, story_id=1, name="画布", definition_revision=3)

    class Db:
        def get(self, *_): return canvas
        def close(self): pass

    monkeypatch.setattr(agent_service, "SessionLocal", lambda: Db())
    ctx = agent_service.AgentRunContext(
        story_id=1, api_key=None, pending_changes=agent_service.PendingChangesTracker(),
        workflow_type="video_canvas", workflow_id=5, canvas_graph_snapshot=graph,
        canvas_graph_write_mode="local", canvas_client_revision=9,
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(ctx)
    try:
        result = asyncio.run(agent_service.apply_canvas_ops(5, [{"op": "update_node", "node_id": "text-1", "data": {"label": "新"}}], 3))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)
    assert result["ok"] is True
    assert result["write_mode"] == "local"
    assert result["client_revision"] == 9
    assert result["graph"]["nodes"][0]["data"]["label"] == "新"
