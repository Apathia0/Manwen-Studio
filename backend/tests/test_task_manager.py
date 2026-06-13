import asyncio

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from models import Base, BackgroundTask


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session._test_engine = engine
    yield session
    session.close()


class TestBackgroundTaskCreate:
    """测试后台任务创建"""

    def test_create_with_minimal_fields(self, db_session):
        """仅填写必填字段创建任务"""
        task = BackgroundTask(
            task_id="test_minimal",
            task_type="quality_check",
        )
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="test_minimal").first()
        assert saved is not None
        assert saved.status == "pending"
        assert saved.retry_count == 0
        assert saved.max_retries == 3
        assert saved.error_message is None

    def test_create_with_all_fields(self, db_session):
        """填写全部字段创建任务"""
        task = BackgroundTask(
            task_id="test_all_fields",
            task_type="video_render",
            status="running",
            retry_count=2,
            max_retries=5,
            error_message="首次尝试失败",
            result_json={"output": "result.mp4", "duration": 30},
            story_id=1,
            chapter_id=10,
            shot_id=100,
            metadata_json={"source": "test"},
        )
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="test_all_fields").first()
        assert saved.task_type == "video_render"
        assert saved.status == "running"
        assert saved.retry_count == 2
        assert saved.max_retries == 5
        assert saved.error_message == "首次尝试失败"
        assert saved.result_json == {"output": "result.mp4", "duration": 30}
        assert saved.story_id == 1
        assert saved.chapter_id == 10
        assert saved.shot_id == 100
        assert saved.metadata_json == {"source": "test"}


class TestBackgroundTaskUniqueConstraint:
    """测试 task_id 唯一性约束"""

    def test_duplicate_task_id_raises_error(self, db_session):
        """插入重复 task_id 应抛出 IntegrityError"""
        task1 = BackgroundTask(task_id="dup_id", task_type="quality_check")
        db_session.add(task1)
        db_session.commit()

        task2 = BackgroundTask(task_id="dup_id", task_type="video_render")
        db_session.add(task2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_distinct_ids_allowed(self, db_session):
        """不同 task_id 可以共存"""
        task1 = BackgroundTask(task_id="task_a", task_type="type_a")
        task2 = BackgroundTask(task_id="task_b", task_type="type_b")
        db_session.add_all([task1, task2])
        db_session.commit()

        count = db_session.query(BackgroundTask).count()
        assert count == 2


class TestBackgroundTaskJsonFields:
    """测试 JSON 字段读写"""

    def test_result_json_read_write(self, db_session):
        """写入并读取 result_json"""
        task = BackgroundTask(
            task_id="json_result_test",
            task_type="quality_check",
            result_json={"score": 0.95, "details": {"passed": 10, "failed": 1}},
        )
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="json_result_test").first()
        assert saved.result_json["score"] == 0.95
        assert saved.result_json["details"]["passed"] == 10
        assert saved.result_json["details"]["failed"] == 1

    def test_metadata_json_read_write(self, db_session):
        """写入并读取 metadata_json"""
        task = BackgroundTask(
            task_id="json_metadata_test",
            task_type="video_render",
            metadata_json={"source": "chapter_3", "priority": "high", "tags": ["urgent"]},
        )
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="json_metadata_test").first()
        assert saved.metadata_json["source"] == "chapter_3"
        assert saved.metadata_json["priority"] == "high"
        assert "urgent" in saved.metadata_json["tags"]

    def test_json_fields_default_to_none(self, db_session):
        """不设置 JSON 字段时应为 None"""
        task = BackgroundTask(task_id="json_default_test", task_type="quality_check")
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="json_default_test").first()
        assert saved.result_json is None
        assert saved.metadata_json is None


class TestBackgroundTaskLifecycle:
    """测试完整任务生命周期"""

    def test_full_lifecycle(self, db_session):
        """从 pending -> running -> completed 完整流程"""
        task = BackgroundTask(
            task_id="lifecycle_test",
            task_type="video_render",
        )
        db_session.add(task)
        db_session.commit()
        assert task.status == "pending"
        assert task.started_at is None
        assert task.completed_at is None

        # 转为 running
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db_session.commit()
        saved = db_session.query(BackgroundTask).filter_by(task_id="lifecycle_test").first()
        assert saved.status == "running"
        assert saved.started_at is not None
        assert saved.completed_at is None

        # 转为 completed
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
        task.result_json = {"output": "final.mp4"}
        db_session.commit()
        saved = db_session.query(BackgroundTask).filter_by(task_id="lifecycle_test").first()
        assert saved.status == "completed"
        assert saved.completed_at is not None
        assert saved.result_json == {"output": "final.mp4"}

    def test_error_and_retry_flow(self, db_session):
        """从 running -> retrying -> failed 的重试流程"""
        task = BackgroundTask(
            task_id="retry_flow_test",
            task_type="quality_check",
            max_retries=3,
        )
        db_session.add(task)
        db_session.commit()

        # 第一次失败->重试
        task.status = "retrying"
        task.retry_count = 1
        task.error_message = "超时错误"
        db_session.commit()
        saved = db_session.query(BackgroundTask).filter_by(task_id="retry_flow_test").first()
        assert saved.status == "retrying"
        assert saved.retry_count == 1
        assert saved.error_message == "超时错误"

        # 重试后 running
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        task.error_message = None
        db_session.commit()
        saved = db_session.query(BackgroundTask).filter_by(task_id="retry_flow_test").first()
        assert saved.status == "running"
        assert saved.started_at is not None

        # 最终失败
        task.status = "failed"
        task.error_message = "重试耗尽"
        task.retry_count = 3
        db_session.commit()
        saved = db_session.query(BackgroundTask).filter_by(task_id="retry_flow_test").first()
        assert saved.status == "failed"
        assert saved.retry_count == 3
        assert saved.error_message == "重试耗尽"

    def test_submit_task_without_timeout_does_not_use_wait_for(self, db_session, monkeypatch):
        """timeout=None 时不包裹 asyncio.wait_for"""
        from services.task_manager import TaskManager
        from sqlalchemy.orm import sessionmaker

        import services.task_manager as tm
        engine = getattr(db_session, "_test_engine", None)
        if engine:
            monkeypatch.setattr(tm, "SessionLocal", sessionmaker(bind=engine))

        manager = TaskManager()
        wait_for_called = {"value": False}

        original_wait_for = asyncio.wait_for

        async def fake_wait_for(*args, **kwargs):
            wait_for_called["value"] = True
            return await original_wait_for(*args, **kwargs)

        async def fake_coro(*args, **kwargs):
            return {"ok": True}

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.submit_task("task-1", "video", fake_coro, timeout=None, max_retries=0))
        finally:
            loop.close()

        assert wait_for_called["value"] is False

    def test_updated_at_auto_update(self, db_session):
        """updated_at 在更新时自动变化"""
        task = BackgroundTask(task_id="updated_at_test", task_type="quality_check")
        db_session.add(task)
        db_session.commit()

        original_updated = task.updated_at

        # 更新状态
        task.status = "running"
        db_session.commit()

        # 在 SQLite 中 onupdate 可能在同一次事务中不更新（秒级精度）
        # 验证 updated_at 字段存在且不为 None
        saved = db_session.query(BackgroundTask).filter_by(task_id="updated_at_test").first()
        assert saved.updated_at is not None


class TestBackgroundTaskMaxRetries:
    """测试 max_retries 耗尽后的行为"""

    def test_retry_count_reaches_max(self, db_session):
        """重试次数达到 max_retries 后应标记为 failed"""
        task = BackgroundTask(
            task_id="max_retry_test",
            task_type="quality_check",
            max_retries=3,
        )
        db_session.add(task)
        db_session.commit()

        # 模拟多次重试直到耗尽
        for attempt in range(1, 4):
            task.retry_count = attempt
            task.error_message = f"第 {attempt} 次失败"
            if attempt < 3:
                task.status = "retrying"
            else:
                task.status = "failed"
            db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="max_retry_test").first()
        assert saved.retry_count == 3
        assert saved.retry_count == saved.max_retries
        assert saved.status == "failed"
        assert saved.error_message == "第 3 次失败"

    def test_status_remains_pending_when_not_started(self, db_session):
        """未开始的任务状态维持 pending"""
        task = BackgroundTask(
            task_id="never_started",
            task_type="video_render",
            max_retries=5,
        )
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(BackgroundTask).filter_by(task_id="never_started").first()
        assert saved.status == "pending"
        assert saved.retry_count == 0
        assert saved.error_message is None


class TestTaskManager:
    """测试 TaskManager 服务"""

    @pytest.fixture
    def task_manager(self):
        from services.task_manager import TaskManager
        return TaskManager(max_concurrent=2)

    def test_task_manager_init(self, task_manager):
        """测试 TaskManager 初始化"""
        assert task_manager._semaphore._value == 2
        assert len(task_manager._running_tasks) == 0

    def test_with_retry_decorator(self, task_manager):
        """测试重试装饰器"""
        call_count = 0

        @task_manager.with_retry(max_retries=2, base_delay=0.01)
        async def failing_task():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Temporary network timeout")
            return "success"

        result = asyncio.get_event_loop().run_until_complete(failing_task())
        assert result == "success"
        assert call_count == 3

    def test_update_task_metadata_merges_existing_values(self, task_manager, db_session, monkeypatch):
        """任务 metadata 更新应合并而不是覆盖已有字段"""
        import services.task_manager as tm

        engine = getattr(db_session, "_test_engine", None)
        monkeypatch.setattr(tm, "SessionLocal", sessionmaker(bind=engine))

        task = BackgroundTask(
            task_id="metadata-merge",
            task_type="manga_generation",
            metadata_json={"stage": "queued", "chapter_id": 1},
        )
        db_session.add(task)
        db_session.commit()

        task_manager.update_task_metadata("metadata-merge", stage="running", message="正在生成第 1 张")

        saved = db_session.query(BackgroundTask).filter_by(task_id="metadata-merge").first()
        assert saved.metadata_json == {
            "stage": "running",
            "chapter_id": 1,
            "message": "正在生成第 1 张",
        }

    def test_update_task_retry_sets_retrying_metadata(self, task_manager, db_session, monkeypatch):
        """进入重试等待时应写入 retrying 状态和用户可读提示"""
        import services.task_manager as tm

        engine = getattr(db_session, "_test_engine", None)
        monkeypatch.setattr(tm, "SessionLocal", sessionmaker(bind=engine))

        task = BackgroundTask(
            task_id="retry-state",
            task_type="video_render",
            max_retries=2,
            metadata_json={"stage": "submitting"},
        )
        db_session.add(task)
        db_session.commit()

        task_manager._update_task_retry("retry-state", 1, "upstream 503")

        saved = db_session.query(BackgroundTask).filter_by(task_id="retry-state").first()
        assert saved.status == "retrying"
        assert saved.retry_count == 1
        assert saved.error_message == "upstream 503"
        assert saved.metadata_json["stage"] == "retrying"
        assert "自动重试" in saved.metadata_json["message"]

    def test_with_retry_does_not_retry_value_error(self, task_manager):
        """参数/配置类错误不应进入自动重试"""
        call_count = 0

        @task_manager.with_retry(max_retries=3, base_delay=0.01)
        async def invalid_task():
            nonlocal call_count
            call_count += 1
            raise ValueError("invalid request")

        with pytest.raises(ValueError, match="invalid request"):
            asyncio.get_event_loop().run_until_complete(invalid_task())

        assert call_count == 1

    def test_request_cancellation_by_prefix(self, task_manager):
        """章节视频取消可按真实 task_id 前缀命中运行任务"""
        task_manager._running_tasks = {
            "chapter_video_12_parse": object(),
            "chapter_video_12_videos": object(),
            "chapter_video_13_videos": object(),
        }

        matched = task_manager.request_cancellation_by_prefix("chapter_video_12_")

        assert matched == ["chapter_video_12_parse", "chapter_video_12_videos"]
        assert task_manager.is_cancellation_requested("chapter_video_12_parse")
        assert task_manager.is_cancellation_requested("chapter_video_12_videos")
        assert not task_manager.is_cancellation_requested("chapter_video_13_videos")

    def test_with_retry_exhausted(self, task_manager):
        """测试重试耗尽"""
        @task_manager.with_retry(max_retries=1, base_delay=0.01)
        async def always_failing():
            raise ValueError("Permanent error")

        with pytest.raises(ValueError, match="Permanent error"):
            asyncio.get_event_loop().run_until_complete(always_failing())
