"""画布助手文本化读取：大纲、搜索、按字段精读、生成状态（不依赖看图）。"""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import VideoCanvas, VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion
from services.canvas_agent_reading import build_outline, node_status_map, search_nodes, select_fields


def _graph():
    return {
        "nodes": [
            {"id": "script", "type": "screenplay", "data": {"label": "剧本", "config": {"content": "萧炎走上前，手按在测验魔石碑上。测验员宣读：斗之力，三段！"}}},
            {"id": "img-1", "type": "image", "data": {"label": "分镜1：三段废物", "config": {"prompt": "测验员右手按在魔石碑上，碑面发光", "duration_seconds": 5}}},
            {"id": "img-2", "type": "image", "data": {"label": "分镜2：嘲笑", "config": {"prompt": "人群窃窃私语，萧炎握拳"}}},
            {"id": "vid-1", "type": "video", "data": {"label": "镜头1", "config": {"prompt": "镜头推近魔石碑", "storyboard_json": {"segments": [{"visual_action": "测验员抬手"}]}}}},
        ],
        "edges": [{"id": "e1", "source": "script", "target": "img-1"}, {"id": "e2", "source": "img-1", "target": "vid-1"}],
    }


@pytest.fixture
def run_db():
    engine = create_engine("sqlite:///:memory:")
    for model in (VideoCanvas, VideoCanvasVersion, VideoCanvasRun, VideoCanvasRunNode):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add(VideoCanvas(id=1, owner_user_id=2, story_id=3, name="画布", definition_revision=2))
    old = _graph()
    db.add(VideoCanvasVersion(id=1, canvas_id=1, version_no=1, graph_json=old, source="agent"))
    db.add(VideoCanvasRun(id=10, canvas_id=1, canvas_version_id=1, status="succeeded"))
    db.add(VideoCanvasRunNode(run_id=10, node_id="img-1", node_type="image", attempt=1, status="succeeded", output_snapshot_json={"url": "/static/manga/a.png"}))
    db.add(VideoCanvasRunNode(run_id=10, node_id="img-2", node_type="image", attempt=1, status="failed", error_message="内容安全策略拦截"))
    db.commit()
    yield db
    db.close()
    engine.dispose()


def test_status_map_reports_generated_failed_missing_and_stale_as_text(run_db):
    current = _graph()
    current["nodes"][1]["data"]["config"]["prompt"] = "萧炎的手按在魔石碑上"  # 出图之后改过提示词
    statuses = node_status_map(run_db, 1, current)
    assert statuses["img-1"]["status"] == "succeeded" and statuses["img-1"]["stale"] is True and statuses["img-1"]["has_media"]
    assert statuses["img-2"]["status"] == "failed" and "内容安全" in statuses["img-2"]["error"] and statuses["img-2"]["stale"] is False
    assert statuses["vid-1"]["status"] == "not_generated"
    assert "script" not in statuses, "非媒体节点没有生成状态"


def test_outline_is_compact_and_supports_filters_and_paging(run_db):
    graph = _graph()
    statuses = node_status_map(run_db, 1, graph)
    outline = build_outline(graph, statuses)
    assert outline["total_nodes"] == 4 and outline["type_counts"] == {"screenplay": 1, "image": 2, "video": 1}
    row = next(item for item in outline["nodes"] if item["id"] == "img-2")
    assert row["status"] == "失败" and row["error"] == "内容安全策略拦截" and row["in"] == 0
    assert all(len(item["text_head"]) <= 61 for item in outline["nodes"]), "大纲不含提示词全文"
    assert [item["id"] for item in build_outline(graph, statuses, status_filter=["failed"])["nodes"]] == ["img-2"]
    assert [item["id"] for item in build_outline(graph, statuses, node_types=["video"])["nodes"]] == ["vid-1"]
    page = build_outline(graph, statuses, offset=1, limit=2)
    assert page["returned"] == 2 and page["has_more"] is True and page["nodes"][0]["id"] == "img-1"


def test_outline_stale_filter_finds_outputs_that_no_longer_match_prompt(run_db):
    graph = _graph()
    graph["nodes"][1]["data"]["config"]["prompt"] = "改过的提示词"
    statuses = node_status_map(run_db, 1, graph)
    stale = build_outline(graph, statuses, status_filter=["stale"])
    assert [item["id"] for item in stale["nodes"]] == ["img-1"] and "已过期" in stale["nodes"][0]["status"]


def test_search_finds_the_node_by_text_like_grep():
    result = search_nodes(_graph(), "测验员")
    hits = {(item["node_id"], item["field"]) for item in result["matches"]}
    assert ("img-1", "prompt") in hits and ("script", "content") in hits and ("vid-1", "storyboard_json") in hits
    snippet = next(item["snippet"] for item in result["matches"] if item["node_id"] == "img-1")
    assert "测验员右手按在魔石碑上" in snippet
    only_prompts = search_nodes(_graph(), "测验员", node_types=["image"], fields=["prompt"])
    assert [item["node_id"] for item in only_prompts["matches"]] == ["img-1"]
    assert search_nodes(_graph(), r"分镜\d", regex=True)["total_matches"] == 2
    assert "error" in search_nodes(_graph(), "(", regex=True) and "error" in search_nodes(_graph(), "  ")
    capped = search_nodes(_graph(), "魔石碑", limit=1)
    assert capped["returned"] == 1 and capped["truncated"] is True


def test_select_fields_reads_only_requested_config_keys():
    node = _graph()["nodes"][1]
    picked = select_fields(node, ["prompt", "missing"])
    assert picked["config"] == {"prompt": "测验员右手按在魔石碑上，碑面发光"}
    assert picked["missing_fields"] == ["missing"] and "duration_seconds" in picked["available_fields"]
    assert select_fields(node, None) == node["data"]


def test_canvas_reading_tools_run_through_the_registry(run_db, monkeypatch):
    from services import agent_service as agent

    monkeypatch.setattr(agent, "SessionLocal", lambda: run_db)
    monkeypatch.setattr(run_db, "close", lambda: None)
    monkeypatch.setattr(agent, "_require_current_video_canvas", lambda db, canvas_id: db.get(VideoCanvas, canvas_id))
    context = agent.AgentRunContext(
        story_id=3, api_key="k", pending_changes=agent.PendingChangesTracker(),
        pending_change_key=agent.AgentPendingChangeKey(user_id=2, story_id=3, conversation_id=5),
        workflow_type="video_canvas", workflow_id=1, canvas_permission_mode="ask", canvas_graph_snapshot=_graph(),
    )
    token = agent._AGENT_RUN_CONTEXT.set(context)
    try:
        outline = json.loads(asyncio.run(agent.tool_registry.execute("get_canvas_outline", {"canvas_id": 1})))
        assert outline["total_nodes"] == 4
        found = json.loads(asyncio.run(agent.tool_registry.execute("search_canvas_nodes", {"canvas_id": 1, "query": "右手"})))
        assert found["matches"][0]["node_id"] == "img-1"
        read = json.loads(asyncio.run(agent.tool_registry.execute("get_canvas_nodes", {"canvas_id": 1, "node_ids": ["img-1"], "fields": ["prompt"]})))
        node = read["nodes"][0]
        assert node["data"]["config"] == {"prompt": "测验员右手按在魔石碑上，碑面发光"}
        assert node["generation"]["status"] == "succeeded"
    finally:
        agent._AGENT_RUN_CONTEXT.reset(token)


def test_observation_puts_current_prompt_next_to_each_image(tmp_path):
    from services.agent_media import canvas_observation_content

    path = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "red").save(path)
    content = canvas_observation_content("摘要", [{"filename": "画布媒体观察[node=img-1]", "path": str(path), "node_id": "img-1", "prompt_excerpt": "萧炎的手按在魔石碑上", "detail": "low"}])
    labels = [item["text"] for item in content if item.get("type") == "text"]
    assert any("当前提示词：萧炎的手按在魔石碑上" in text for text in labels)
    assert sum(1 for item in content if item.get("type") == "image_url") == 1
