"""节点候选结果：按时间倒序、素材去重、校验素材归属。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import VideoAsset, VideoCanvasRun, VideoCanvasRunNode
from services.canvas_candidates import list_node_candidates


def make_db():
    engine = create_engine("sqlite:///:memory:")
    for table in (VideoAsset.__table__, VideoCanvasRun.__table__, VideoCanvasRunNode.__table__):
        table.create(engine)
    return engine


def add_run(db, run_id, node_id, asset_id, *, status="succeeded", url="/static/x.png", minutes=0):
    db.add(VideoCanvasRun(id=run_id, canvas_id=1, canvas_version_id=1, status="succeeded", plan_json={}, created_at=datetime(2026, 1, 1) + timedelta(minutes=minutes)))
    db.add(VideoCanvasRunNode(run_id=run_id, node_id=node_id, node_type="image", attempt=1, status=status, output_snapshot_json={"asset_id": asset_id, "url": url}))


def test_candidates_are_distinct_newest_first_and_current_marked():
    engine = make_db()
    with Session(engine) as db:
        for asset_id in (10, 11):
            db.add(VideoAsset(id=asset_id, story_id=3, asset_type="storyboard_frame", name="a", file_path=f"p{asset_id}.png", provider="image2", prompt="p", usage_scope="story_shared"))
        add_run(db, 1, "n", 10, minutes=1)
        add_run(db, 2, "n", 11, minutes=2)
        add_run(db, 3, "n", 11, minutes=3)
        add_run(db, 4, "n", 10, status="failed", minutes=4)
        add_run(db, 5, "other", 10, minutes=5)
        db.commit()
        canvas = SimpleNamespace(id=1, story_id=3)
        result = list_node_candidates(db, canvas=canvas, node_id="n", current_asset_id=None)
        assert [c["asset_id"] for c in result] == [11, 10]
        assert [c["is_current"] for c in result] == [True, False]
        pinned = list_node_candidates(db, canvas=canvas, node_id="n", current_asset_id=10)
        assert [c["is_current"] for c in pinned] == [False, True]


def test_assets_from_other_story_or_deleted_are_excluded():
    engine = make_db()
    with Session(engine) as db:
        db.add(VideoAsset(id=20, story_id=99, asset_type="storyboard_frame", name="a", file_path="p.png", provider="image2", prompt="p", usage_scope="story_shared"))
        add_run(db, 1, "n", 20)
        add_run(db, 2, "n", 21)
        db.commit()
        assert list_node_candidates(db, canvas=SimpleNamespace(id=1, story_id=3), node_id="n", current_asset_id=None) == []
