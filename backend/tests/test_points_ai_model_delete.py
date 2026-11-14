from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AiChannel, AiModel, AiTaskDefault, AiUsageEvent, CreationStudioJob, User, UserAiPreference
from routers import points_ai


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _model(db_session):
    channel = AiChannel(code="delete-test", name="删除测试", base_url="https://example.com", modality="video")
    db_session.add(channel)
    db_session.flush()
    model = AiModel(
        channel_id=channel.id,
        model_key="delete-test-model",
        display_name="删除测试模型",
        modality="video",
    )
    db_session.add(model)
    db_session.commit()
    return model


def test_admin_delete_model_rejects_business_references(monkeypatch, db_session):
    model = _model(db_session)
    user = User(email="delete-model@example.com", password_hash="hash", name="删除测试")
    db_session.add(user)
    db_session.flush()
    db_session.add_all(
        [
            AiTaskDefault(task_type="creation_studio.video", model_id=model.id),
            UserAiPreference(user_id=user.id, default_video_model_id=model.id),
            CreationStudioJob(owner_user_id=user.id, media_kind="video", prompt="测试", model_id=model.id),
            AiUsageEvent(request_id="delete-model-usage", user_id=user.id, model_id=model.id),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))

    with pytest.raises(HTTPException) as exc_info:
        points_ai.admin_delete_model(model.id, SimpleNamespace(), db_session)

    assert exc_info.value.status_code == 409
    assert "任务默认模型" in str(exc_info.value.detail)
    assert "用户默认模型" in str(exc_info.value.detail)
    assert "创作台任务" in str(exc_info.value.detail)
    assert "计费用量记录" in str(exc_info.value.detail)
    assert db_session.get(AiModel, model.id) is not None


def test_admin_delete_model_deletes_unreferenced_model(monkeypatch, db_session):
    model = _model(db_session)
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))

    result = points_ai.admin_delete_model(model.id, SimpleNamespace(), db_session)

    assert result == {"ok": True, "model_id": model.id}
    assert db_session.get(AiModel, model.id) is None

