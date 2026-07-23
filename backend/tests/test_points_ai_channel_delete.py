from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AiChannel, AiModel, AiTaskDefault, AiUsageEvent, User, UserAiPreference
from routers import points_ai


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _channel_with_model(db_session):
    channel = AiChannel(
        code="channel-delete-test",
        name="渠道删除测试",
        base_url="https://example.com/v1",
        modality="text",
    )
    db_session.add(channel)
    db_session.flush()
    model = AiModel(
        channel_id=channel.id,
        model_key="channel-delete-model",
        display_name="渠道删除模型",
        modality="text",
    )
    db_session.add(model)
    db_session.commit()
    return channel, model


def test_list_user_channels_only_returns_enabled_configured_channels(monkeypatch, db_session):
    db_session.add_all(
        [
            AiChannel(code="visible", name="可见渠道", base_url="https://example.com/v1", modality="text"),
            AiChannel(code="disabled", name="停用渠道", base_url="https://disabled.example.com/v1", modality="image", enabled=False),
            AiChannel(code="empty", name="空地址渠道", base_url="", modality="video"),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(points_ai, "_require_user", lambda *_args: SimpleNamespace(id=1))

    result = points_ai.list_user_channels(SimpleNamespace(), db_session)

    assert [channel["code"] for channel in result["channels"]] == ["visible"]
    assert "platform_secret_ciphertext" not in result["channels"][0]


def test_admin_delete_channel_rejects_model_references(monkeypatch, db_session):
    channel, model = _channel_with_model(db_session)
    user = User(email="channel-delete@example.com", password_hash="hash", name="删除测试")
    db_session.add(user)
    db_session.flush()
    db_session.add_all(
        [
            AiTaskDefault(task_type="channel.delete", model_id=model.id),
            UserAiPreference(user_id=user.id, default_text_model_id=model.id),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))

    with pytest.raises(HTTPException) as exc_info:
        points_ai.admin_delete_channel(channel.id, SimpleNamespace(), db_session)

    assert exc_info.value.status_code == 409
    assert "任务默认模型" in str(exc_info.value.detail)
    assert "用户默认模型" in str(exc_info.value.detail)


def test_admin_delete_channel_rejects_direct_usage_reference(monkeypatch, db_session):
    channel, _model = _channel_with_model(db_session)
    user = User(email="channel-usage@example.com", password_hash="hash", name="用量测试")
    db_session.add(user)
    db_session.flush()
    db_session.add(AiUsageEvent(request_id="channel-usage", user_id=user.id, channel_id=channel.id))
    db_session.commit()
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))

    with pytest.raises(HTTPException) as exc_info:
        points_ai.admin_delete_channel(channel.id, SimpleNamespace(), db_session)

    assert exc_info.value.status_code == 409
    assert "计费用量记录" in str(exc_info.value.detail)


def test_admin_delete_channel_cascades_unreferenced_models(monkeypatch, db_session):
    channel, model = _channel_with_model(db_session)
    channel_id = channel.id
    model_id = model.id
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))

    result = points_ai.admin_delete_channel(channel_id, SimpleNamespace(), db_session)

    assert result == {"ok": True, "channel_id": channel_id}
    assert db_session.get(AiChannel, channel_id) is None
    assert db_session.get(AiModel, model_id) is None
