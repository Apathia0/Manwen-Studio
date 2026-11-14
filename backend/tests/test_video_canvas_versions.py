"""画布版本历史、差异预览与恢复接口测试（直接调用路由函数，使用内存 SQLite）。"""

import asyncio
import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import VideoCanvas, VideoCanvasLayout, VideoCanvasRun, VideoCanvasVersion
from routers import video_canvas as router
from services.agent_service import PendingChange, PendingChangesTracker


def _graph(prompt):
    return {
        "schema_version": 1,
        "nodes": [{"id": "img-1", "type": "image", "position": {"x": 0, "y": 0}, "data": {"label": "分镜", "config": {"prompt": prompt}}}],
        "edges": [],
        "groups": [],
        "metadata": {},
    }


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    for model in (VideoCanvas, VideoCanvasVersion, VideoCanvasLayout, VideoCanvasRun):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(VideoCanvas(id=1, owner_user_id=2, story_id=3, name="画布", definition_revision=3))
    for number, (source, prompt) in enumerate([("manual", "初稿"), ("agent", "助手改写"), ("manual", "用户再改")], start=1):
        session.add(VideoCanvasVersion(canvas_id=1, version_no=number, graph_json=_graph(prompt), source=source, change_summary=f"第{number}次"))
    session.commit()
    monkeypatch.setattr(router, "_require_user", lambda request, db: SimpleNamespace(id=2))
    yield session
    session.close()
    engine.dispose()


def _run(coro):
    return asyncio.run(coro)


def test_list_versions_newest_first_with_current_flag(db):
    result = _run(router.list_video_canvas_versions(1, SimpleNamespace(), 30, db))
    assert [item["version_no"] for item in result["versions"]] == [3, 2, 1]
    assert [item["is_current"] for item in result["versions"]] == [True, False, False]
    assert result["versions"][1]["source"] == "agent" and result["versions"][0]["node_count"] == 1


def test_diff_shows_what_restore_would_change(db):
    result = _run(router.diff_video_canvas_version(1, 2, SimpleNamespace(), db))
    change = result["diff"]["nodes"][0]["changes"][0]
    assert change == {"field": "data.config.prompt", "before": "用户再改", "after": "助手改写"}


def test_restore_appends_new_version_without_rewriting_history(db):
    body = router.VideoCanvasVersionRestore(expected_definition_revision=3)
    result = _run(router.restore_video_canvas_version(1, 1, body, SimpleNamespace(), db))
    assert result["version"]["version_no"] == 4
    assert result["version"]["graph"]["nodes"][0]["data"]["config"]["prompt"] == "初稿"
    rows = db.query(VideoCanvasVersion).order_by(VideoCanvasVersion.version_no).all()
    assert [row.version_no for row in rows] == [1, 2, 3, 4]
    assert rows[3].source == "restore" and "版本 1" in rows[3].change_summary
    assert rows[2].graph_json["nodes"][0]["data"]["config"]["prompt"] == "用户再改", "历史版本保持不变"


def test_restore_rejects_stale_revision_missing_version_and_current(db):
    with pytest.raises(HTTPException) as stale:
        _run(router.restore_video_canvas_version(1, 1, router.VideoCanvasVersionRestore(expected_definition_revision=2), SimpleNamespace(), db))
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        _run(router.restore_video_canvas_version(1, 99, router.VideoCanvasVersionRestore(expected_definition_revision=3), SimpleNamespace(), db))
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as current:
        _run(router.restore_video_canvas_version(1, 3, router.VideoCanvasVersionRestore(expected_definition_revision=3), SimpleNamespace(), db))
    assert current.value.status_code == 400


def test_other_users_cannot_read_or_restore(db, monkeypatch):
    monkeypatch.setattr(router, "_require_user", lambda request, db: SimpleNamespace(id=99))
    with pytest.raises(HTTPException) as listed:
        _run(router.list_video_canvas_versions(1, SimpleNamespace(), 30, db))
    assert listed.value.status_code == 403
    with pytest.raises(HTTPException) as restored:
        _run(router.restore_video_canvas_version(1, 1, router.VideoCanvasVersionRestore(expected_definition_revision=3), SimpleNamespace(), db))
    assert restored.value.status_code == 404


# ── canvas_stage 写入纳入撤回记录 ─────────────────────────

def test_canvas_stage_graph_change_is_registered_for_rollback(monkeypatch):
    from services import agent_service as service

    tracker = PendingChangesTracker()
    monkeypatch.setattr(service, "_current_pending_changes", lambda: tracker)
    monkeypatch.setattr(service, "_persist_tracker_write_ahead", lambda *_a, **_k: None)
    versions = iter([
        SimpleNamespace(version_no=4, graph_json=_graph("阶段后")),
    ])
    monkeypatch.setattr(service, "_latest_canvas_version_row", lambda canvas_id: next(versions))

    class _NameDb:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, key):
            return SimpleNamespace(name="漫剧画布")

    monkeypatch.setattr(service, "SessionLocal", lambda: _NameDb())
    before = SimpleNamespace(version_no=3, graph_json=_graph("阶段前"))
    service._record_canvas_stage_graph_change(1, before)
    changes = tracker._changes
    assert len(changes) == 1
    assert changes[0].type == "video_canvas_graph" and changes[0].display_name == "漫剧画布"
    assert changes[0].old_value["nodes"][0]["data"]["config"]["prompt"] == "阶段前"
    assert changes[0].new_value["nodes"][0]["data"]["config"]["prompt"] == "阶段后"
    assert len(tracker.get_summary()) == 1, "new_value 已填充，应出现在待确认摘要中"


def test_canvas_stage_without_graph_change_registers_nothing(monkeypatch):
    from services import agent_service as service

    tracker = PendingChangesTracker()
    monkeypatch.setattr(service, "_current_pending_changes", lambda: tracker)
    same = SimpleNamespace(version_no=3, graph_json=_graph("不变"))
    monkeypatch.setattr(service, "_latest_canvas_version_row", lambda canvas_id: copy.copy(same))
    service._record_canvas_stage_graph_change(1, same)
    assert not tracker.has_changes()
    service._record_canvas_stage_graph_change(1, None)
    assert not tracker.has_changes()
    assert PendingChange  # 引用以避免未使用导入告警
