"""章节删除（delete_chapter）回归测试：验证无 CASCADE 子表全部被显式清理且顺序正确。"""

import asyncio
from types import SimpleNamespace

from sqlalchemy.sql.expression import literal

import main


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _model_name(model):
    """从模型类或 InstrumentedAttribute 提取模型类名。"""
    cls = getattr(model, "class_", None)
    if cls is not None:
        return cls.__name__
    return getattr(model, "__name__", repr(model))


class _SqlLike:
    """可被真实 SQLAlchemy 表达式（in_/or_）接受的假对象。"""

    def __clause_element__(self):
        return literal(1)


class _Q(_SqlLike):
    """记录 query 调用链的假 Query。"""

    def __init__(self, recorder, model):
        self._recorder = recorder
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def subquery(self):
        return _SqlLike()

    def delete(self, synchronize_session=False):
        self._recorder.calls.append(("delete", _model_name(self._model)))

    def all(self):
        return []

    def first(self):
        return None


class _Db:
    """记录删除调用顺序的假 Session。"""

    def __init__(self):
        self.calls = []  # [("delete", model_name) | ("db_delete", model_name)]

    def query(self, model):
        return _Q(self, model)

    def delete(self, obj):
        self.calls.append(("db_delete", _model_name(obj)))

    def commit(self):
        pass


def _run_delete(monkeypatch):
    """执行 delete_chapter，返回调用记录。"""
    chapter = SimpleNamespace(id=7, story_id=1, images=[], messages=[], cover_image=None)
    recorder = _Db()
    monkeypatch.setattr(main, "_require_user", lambda request, db: SimpleNamespace())
    monkeypatch.setattr(
        main, "_require_chapter_for_user", lambda cid, user, db: chapter
    )
    monkeypatch.setattr(main, "_rmtree_best_effort", lambda *a, **k: None)
    result = main.delete_chapter(7, SimpleNamespace(), recorder)
    assert result == {"ok": True}
    return recorder.calls


def test_delete_chapter_cleans_all_non_cascade_tables(monkeypatch):
    """分镜/视频/用量/Agent 会话链的所有无 CASCADE 子表都必须被显式删除。"""
    calls = _run_delete(monkeypatch)
    names = set(name for kind, name in calls if kind == "delete")
    expected = {
        "ShotAssetBinding",
        "RenderedClip",
        "VideoGenerationJob",
        "VideoAsset",
        "VideoShot",
        "ScriptScene",
        "ChapterVideoShot",
        "ChapterVideoWorkflow",
        "VideoProject",
        "AiUsageEvent",
        "AgentPendingChange",
        "AgentAttachment",
        "AgentConversationMessage",
        "AgentConversation",
        "MangaAssetBinding",
        "MangaAsset",
    }
    assert expected <= names


def test_delete_chapter_video_asset_before_scene_and_shot(monkeypatch):
    """VideoAsset 引用 scene_id/shot_id（RESTRICT），必须先于 VideoShot/ScriptScene 删除。"""
    calls = _run_delete(monkeypatch)
    video_asset_idx = next(i for i, (kind, n) in enumerate(calls) if n == "VideoAsset")
    video_shot_idx = next(i for i, (kind, n) in enumerate(calls) if n == "VideoShot")
    script_scene_idx = next(i for i, (kind, n) in enumerate(calls) if n == "ScriptScene")
    assert video_asset_idx < video_shot_idx
    assert video_asset_idx < script_scene_idx


def test_delete_chapter_agent_children_before_conversation(monkeypatch):
    """Agent 子表引用 agent_conversations.id（RESTRICT），必须先于 AgentConversation 删除。"""
    calls = _run_delete(monkeypatch)
    conversation_idx = next(
        i for i, (kind, n) in enumerate(calls) if n == "AgentConversation"
    )
    for child in ("AgentPendingChange", "AgentAttachment", "AgentConversationMessage"):
        child_idx = next(i for i, (kind, n) in enumerate(calls) if n == child)
        assert child_idx < conversation_idx
