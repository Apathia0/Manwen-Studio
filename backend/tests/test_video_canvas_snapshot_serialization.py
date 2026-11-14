"""画布序列化回归：datetime 必须转为 JSON 可序列化字符串。

修复背景：save_video_canvas_snapshot 将 _serialize_canvas 结果写入
VideoCanvasSyncRecord.after_json / result_json（SQLAlchemy JSON 列）。
JSON 列序列化走 json.dumps，datetime 对象会抛
TypeError: Object of type datetime is not JSON serializable。
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from routers.video_canvas import _serialize_canvas, _serialize_plan, _serialize_run


def _canvas_with_datetimes():
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=15,
        story_id=31,
        default_chapter_id=None,
        name="视频创作画布",
        description=None,
        status="draft",
        definition_revision=1,
        layout_revision=1,
        created_at=now,
        updated_at=now,
    )


class _VersionQuery:
    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return SimpleNamespace(id=1, version_no=1, graph_json={"nodes": [], "edges": []}, source="manual")


class _LayoutQuery:
    def filter(self, *_args):
        return self

    def first(self):
        return None


class _Db:
    def query(self, model):
        name = getattr(model, "__name__", str(model))
        if "Version" in name:
            return _VersionQuery()
        return _LayoutQuery()


def test_serialize_canvas_datetime_fields_are_json_serializable():
    payload = _serialize_canvas(_canvas_with_datetimes(), _Db())
    assert payload["created_at"] == "2026-09-23T12:00:00+00:00"
    assert payload["updated_at"] == "2026-09-23T12:00:00+00:00"
    json.dumps(payload, ensure_ascii=False)


def test_serialize_canvas_tolerates_none_timestamps():
    canvas = _canvas_with_datetimes()
    canvas.created_at = None
    canvas.updated_at = None
    payload = _serialize_canvas(canvas, _Db())
    assert payload["created_at"] is None
    assert payload["updated_at"] is None
    json.dumps(payload, ensure_ascii=False)


def test_serialize_run_datetime_fields_are_json_serializable():
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

    class _NodeQuery:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return []

    class _RunDb:
        def query(self, _model):
            return _NodeQuery()

    run = SimpleNamespace(
        id=1,
        canvas_id=15,
        canvas_version_id=1,
        status="succeeded",
        scope_json={},
        plan_json={},
        error_message=None,
        created_at=now,
        completed_at=now,
    )
    payload = _serialize_run(run, _RunDb())
    assert payload["created_at"] == "2026-09-23T12:00:00+00:00"
    assert payload["completed_at"] == "2026-09-23T12:00:00+00:00"
    json.dumps(payload, ensure_ascii=False)


def test_serialize_plan_datetime_fields_are_json_serializable():
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    plan = SimpleNamespace(
        id=1,
        canvas_id=15,
        story_id=31,
        chapter_id=None,
        status="draft",
        revision=1,
        source_snapshot_json={},
        screenplay_json={},
        shot_json={},
        asset_json={},
        canvas_json={},
        execution_json={},
        workflow_id=None,
        applied_canvas_revision=None,
        workflow_sync_revision=None,
        created_at=now,
        updated_at=now,
    )
    payload = _serialize_plan(plan)
    assert payload["created_at"] == "2026-09-23T12:00:00+00:00"
    assert payload["updated_at"] == "2026-09-23T12:00:00+00:00"
    json.dumps(payload, ensure_ascii=False)
