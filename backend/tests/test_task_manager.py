import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, BackgroundTask


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_background_task_create(db_session):
    """测试创建后台任务"""
    task = BackgroundTask(
        task_id="test_task_1",
        task_type="quality_check",
        status="pending",
        max_retries=3,
    )
    db_session.add(task)
    db_session.commit()

    saved = db_session.query(BackgroundTask).filter_by(task_id="test_task_1").first()
    assert saved is not None
    assert saved.status == "pending"
    assert saved.retry_count == 0
    assert saved.max_retries == 3


def test_background_task_status_update(db_session):
    """测试更新任务状态"""
    task = BackgroundTask(task_id="test_task_2", task_type="video_render")
    db_session.add(task)
    db_session.commit()

    task.status = "running"
    task.started_at = datetime.utcnow()
    db_session.commit()

    updated = db_session.query(BackgroundTask).filter_by(task_id="test_task_2").first()
    assert updated.status == "running"
    assert updated.started_at is not None


def test_background_task_retry(db_session):
    """测试重试计数"""
    task = BackgroundTask(
        task_id="test_task_3",
        task_type="quality_check",
        max_retries=3,
    )
    db_session.add(task)
    db_session.commit()

    task.retry_count = 1
    task.last_error = "Connection timeout"
    task.status = "retrying"
    db_session.commit()

    updated = db_session.query(BackgroundTask).filter_by(task_id="test_task_3").first()
    assert updated.retry_count == 1
    assert updated.last_error == "Connection timeout"
    assert updated.status == "retrying"
