"""Agent 多模态附件服务的回归测试。"""

import base64
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentAttachment
from services.agent_media import multimodal_content, resolve_attachments


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_multimodal_image_uses_data_url(tmp_path: Path):
    image_path = tmp_path / "image.png"
    image = Image.new("RGB", (2, 2), "red")
    image.save(image_path, format="PNG")
    payload = multimodal_content(
        "请反推提示词",
        [{"media_kind": "image", "path": str(image_path), "content_type": "image/png", "filename": "image.png"}],
    )
    assert payload[1]["type"] == "image_url"
    assert payload[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(payload[1]["image_url"]["url"].split(",", 1)[1]).startswith(b"\xff\xd8")


def test_multimodal_video_preserves_frame_order(tmp_path: Path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    for path, color in ((first, "red"), (second, "blue")):
        image = Image.new("RGB", (2, 2), color)
        image.save(path, format="JPEG")
    payload = multimodal_content(
        "请生成分镜",
        [{
            "media_kind": "video",
            "filename": "clip.mp4",
            "frame_paths": [str(first), str(second)],
        }],
    )
    frame_payloads = [item["image_url"]["url"] for item in payload if item["type"] == "image_url"]
    assert all(base64.b64decode(item.split(",", 1)[1]).startswith(b"\xff\xd8") for item in frame_payloads)


def test_attachment_cannot_cross_user_or_story(db_session, tmp_path: Path):
    path = tmp_path / "owned.png"
    path.write_bytes(b"owned")
    attachment = AgentAttachment(
        id="attachment-1",
        owner_user_id=10,
        story_id=20,
        original_name="owned.png",
        content_type="image/png",
        file_size=5,
        storage_path=str(path),
        metadata_json={"media_kind": "image"},
    )
    db_session.add(attachment)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        resolve_attachments(["attachment-1"], db=db_session, owner_user_id=11, story_id=20, conversation_id=30)
    assert error.value.status_code == 404
