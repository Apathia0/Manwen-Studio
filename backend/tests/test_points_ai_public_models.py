import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AiChannel, AiModel
from routers import points_ai


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_model(db_session, key, *, modality="text", enabled=True, user_visible=True, channel_enabled=True):
    channel = AiChannel(
        code=f"ch-{key}",
        name=f"渠道-{key}",
        base_url="https://example.com",
        modality=modality,
        enabled=channel_enabled,
    )
    db_session.add(channel)
    db_session.flush()
    model = AiModel(
        channel_id=channel.id,
        model_key=key,
        display_name=f"模型-{key}",
        modality=modality,
        enabled=enabled,
        user_visible=user_visible,
    )
    db_session.add(model)
    db_session.commit()
    return model


def test_public_models_hide_internal_fields_and_filter_invisible(db_session):
    _add_model(db_session, "visible-text")
    _add_model(db_session, "hidden-model", user_visible=False)
    _add_model(db_session, "disabled-model", enabled=False)
    _add_model(db_session, "disabled-channel", channel_enabled=False)

    result = points_ai.list_public_models(modality=None, db=db_session)

    keys = [item["model_key"] for item in result["models"]]
    assert keys == ["visible-text"]
    item = result["models"][0]
    assert "channel_id" not in item
    assert "platform_configured" not in item


def test_public_models_filter_by_modality(db_session):
    _add_model(db_session, "text-model", modality="text")
    _add_model(db_session, "video-model", modality="video")

    result = points_ai.list_public_models(modality="video", db=db_session)

    assert [item["model_key"] for item in result["models"]] == ["video-model"]
