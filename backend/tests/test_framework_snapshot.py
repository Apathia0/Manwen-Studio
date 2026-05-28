"""测试：框架快照/回滚功能。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database import Base
from models import Story, FrameworkSnapshot
from services.framework_utils import (
    _save_framework_snapshot,
    _enforce_framework_snapshot_limit,
    _build_current_snapshot_data,
    restore_framework_snapshot,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def story(db_session: Session) -> Story:
    s = Story(
        title="测试故事",
        description="原始描述",
        tags={"type": "novel"},
        characters=[{"name": "A", "role": "main"}],
        outline={"three_acts": [{"act": 1, "summary": "开头"}]},
    )
    db_session.add(s)
    db_session.commit()
    return s


class TestSaveSnapshot:
    def test_basic_save(self, db_session: Session, story: Story):
        """保存一条基本快照。"""
        data = _build_current_snapshot_data(story)
        snap = _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=data,
            source="panel_adjust",
            reply_summary="测试保存",
            db=db_session,
        )
        assert snap.id is not None
        assert snap.story_id == story.id
        assert snap.snapshot_data["description"] == "原始描述"
        assert snap.source == "panel_adjust"
        assert snap.reply_summary == "测试保存"

    def test_multiple_snapshots_ordered(self, db_session: Session, story: Story):
        """多次保存，后保存的有更大的 id。"""
        data = _build_current_snapshot_data(story)
        snap1 = _save_framework_snapshot(
            story_id=story.id, snapshot_data=data, source="panel_adjust",
            reply_summary="第一次", db=db_session,
        )
        story.description = "修改1"
        db_session.flush()
        data2 = _build_current_snapshot_data(story)
        snap2 = _save_framework_snapshot(
            story_id=story.id, snapshot_data=data2, source="panel_adjust",
            reply_summary="第二次", db=db_session,
        )
        assert snap1.id < snap2.id


class TestEnforceSnapshotLimit:
    def test_keeps_max_count(self, db_session: Session, story: Story):
        """保留最近 max_count 条，删除更早的。"""
        for i in range(25):
            _save_framework_snapshot(
                story_id=story.id,
                snapshot_data=_build_current_snapshot_data(story),
                source="panel_adjust",
                reply_summary=f"快照{i}",
                db=db_session,
            )
        db_session.commit()

        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db_session)
        db_session.commit()

        remaining = db_session.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story.id
        ).order_by(FrameworkSnapshot.created_at.desc()).all()
        assert len(remaining) == 20

    def test_under_limit_unchanged(self, db_session: Session, story: Story):
        """少于 max_count 时不做删除。"""
        for i in range(5):
            _save_framework_snapshot(
                story_id=story.id,
                snapshot_data=_build_current_snapshot_data(story),
                source="panel_adjust",
                reply_summary=f"快照{i}",
                db=db_session,
            )
        db_session.commit()

        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db_session)
        remaining = db_session.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story.id
        ).count()
        assert remaining == 5


class TestRestoreSnapshot:
    def test_restore_basic(self, db_session: Session, story: Story):
        """回滚到指定快照，恢复 4 个字段。"""
        # 保存初始状态
        data1 = _build_current_snapshot_data(story)
        snap1 = _save_framework_snapshot(
            story_id=story.id, snapshot_data=data1, source="panel_adjust",
            reply_summary="初始", db=db_session,
        )
        db_session.commit()

        # 修改 story
        story.description = "修改后描述"
        story.tags = {"type": "modified"}
        story.characters = [{"name": "B"}]
        story.outline = {"three_acts": []}
        db_session.flush()

        # 回滚
        result = restore_framework_snapshot(story, snap1.id, db_session)
        db_session.commit()

        assert story.description == "原始描述"
        assert story.tags == {"type": "novel"}
        assert story.characters == [{"name": "A", "role": "main"}]
        assert story.outline == {"three_acts": [{"act": 1, "summary": "开头"}]}
        # 恢复后的 snapshot_data 与 result 一致
        assert result["description"] == "原始描述"

    def test_restore_creates_auto_snapshot(self, db_session: Session, story: Story):
        """回滚前自动保存当前状态为快照。"""
        data1 = _build_current_snapshot_data(story)
        snap1 = _save_framework_snapshot(
            story_id=story.id, snapshot_data=data1, source="panel_adjust",
            reply_summary="初始", db=db_session,
        )
        db_session.commit()

        story.description = "即将被保存的状态"
        db_session.flush()

        restore_framework_snapshot(story, snap1.id, db_session)
        db_session.commit()

        # 应该有一条 source=auto_before_restore 的快照
        auto_snap = db_session.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story.id,
            FrameworkSnapshot.source == "auto_before_restore",
        ).first()
        assert auto_snap is not None
        assert auto_snap.snapshot_data["description"] == "即将被保存的状态"

    def test_restore_invalid_snapshot(self, db_session: Session, story: Story):
        """回滚不存在的快照应抛出 ValueError。"""
        with pytest.raises(ValueError, match="快照不存在"):
            restore_framework_snapshot(story, 99999, db_session)
