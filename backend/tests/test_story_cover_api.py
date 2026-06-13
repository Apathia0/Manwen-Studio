import asyncio
from pathlib import Path
from types import SimpleNamespace

import main


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self):
        self.committed = False
        self.refreshed = []

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)


class _Request:
    def __init__(self, body):
        self._body = body
        self.state = SimpleNamespace(db=None, current_user=None)

    async def json(self):
        return self._body


def test_store_story_cover_result_keeps_full_url():
    story = SimpleNamespace(cover_image=None)

    result = main._store_story_cover_result(
        story,
        Path("manga_outputs/covers/test.png"),
        "https://oss.aifusion6.cn/manga_outputs/covers/test.png",
    )

    assert result == "https://oss.aifusion6.cn/manga_outputs/covers/test.png"
    assert story.cover_image == "https://oss.aifusion6.cn/manga_outputs/covers/test.png"


def test_store_story_cover_result_falls_back_to_relative_path():
    story = SimpleNamespace(cover_image=None)

    result = main._store_story_cover_result(
        story,
        Path("manga_outputs/covers/test.png"),
        "manga_outputs/covers/test.png",
    )

    assert result == "manga_outputs/covers/test.png"
    assert story.cover_image == "manga_outputs/covers/test.png"


def test_generate_story_cover_persists_oss_url(monkeypatch):
    db = _Db()
    user = SimpleNamespace(id=1)
    story = SimpleNamespace(id=114, cover_image=None)
    output_path = Path("manga_outputs/covers/cover_114_test.png")
    request = _Request({"instruction": "生成封面"})
    oss_url = "https://oss.aifusion6.cn/manga_outputs/covers/cover_114_test.png"

    monkeypatch.setattr(main, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main, "_require_story_for_user", lambda story_id, current_user, db: story)
    monkeypatch.setattr(main, "_build_story_cover_prompt", lambda story, instruction: "prompt")
    monkeypatch.setattr(main, "_story_cover_output_path", lambda story_id: output_path)
    monkeypatch.setattr(main, "_user_image_api_key", lambda request: "img-key")
    monkeypatch.setattr(main, "_check_and_consume_feature_quota", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_release_db_transaction", lambda db: None)

    async def fake_generate_cover_image(prompt, generated_output_path, *, api_key=None, size="1024x1792"):
        assert prompt == "prompt"
        assert generated_output_path == output_path
        assert api_key == "img-key"
        return oss_url

    monkeypatch.setattr(main, "generate_cover_image", fake_generate_cover_image)

    def fail_replace_story_cover_from_path(*args, **kwargs):
        raise AssertionError("OSS 回写场景不应走本地相对路径保存")

    monkeypatch.setattr(main, "_replace_story_cover_from_path", fail_replace_story_cover_from_path)

    result = _run(main.generate_story_cover(114, request, db))

    assert story.cover_image == oss_url
    assert result == {"cover_image": oss_url, "prompt": "prompt"}
    assert db.committed is True
    assert db.refreshed == [story]


def test_generate_story_cover_falls_back_to_relative_path(monkeypatch):
    db = _Db()
    user = SimpleNamespace(id=1)
    story = SimpleNamespace(id=114, cover_image=None)
    output_path = Path("manga_outputs/covers/cover_114_test.png")
    request = _Request({"instruction": "生成封面"})

    monkeypatch.setattr(main, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main, "_require_story_for_user", lambda story_id, current_user, db: story)
    monkeypatch.setattr(main, "_build_story_cover_prompt", lambda story, instruction: "prompt")
    monkeypatch.setattr(main, "_story_cover_output_path", lambda story_id: output_path)
    monkeypatch.setattr(main, "_user_image_api_key", lambda request: "img-key")
    monkeypatch.setattr(main, "_check_and_consume_feature_quota", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_release_db_transaction", lambda db: None)

    async def fake_generate_cover_image(prompt, generated_output_path, *, api_key=None, size="1024x1792"):
        assert prompt == "prompt"
        assert generated_output_path == output_path
        assert api_key == "img-key"
        return str(output_path)

    monkeypatch.setattr(main, "generate_cover_image", fake_generate_cover_image)

    result = _run(main.generate_story_cover(114, request, db))

    assert story.cover_image == "manga_outputs/covers/cover_114_test.png"
    assert result == {"cover_image": "manga_outputs/covers/cover_114_test.png", "prompt": "prompt"}
    assert db.committed is True
    assert db.refreshed == [story]


def test_adjust_story_cover_accepts_remote_cover_url(monkeypatch, tmp_path):
    db = _Db()
    user = SimpleNamespace(id=1)
    story = SimpleNamespace(id=114, cover_image="https://oss.aifusion6.cn/manga_outputs/covers/test.png")
    request = _Request({"instruction": "加一点冷色调"})
    local_source = tmp_path / "downloaded.png"
    local_source.write_bytes(b"fake-image")
    output_path = Path("manga_outputs/covers/cover_114_adjusted.png")
    oss_url = "https://oss.aifusion6.cn/manga_outputs/covers/cover_114_adjusted.png"

    monkeypatch.setattr(main, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main, "_require_story_for_user", lambda story_id, current_user, db: story)
    monkeypatch.setattr(main, "_build_story_cover_prompt", lambda story, instruction: "prompt")
    monkeypatch.setattr(main, "_story_cover_output_path", lambda story_id: output_path)
    monkeypatch.setattr(main, "_user_image_api_key", lambda request: "img-key")
    monkeypatch.setattr(main, "_check_and_consume_feature_quota", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_release_db_transaction", lambda db: None)
    monkeypatch.setattr(main, "ensure_local_media_path", lambda value, kind: str(local_source) if value == story.cover_image and kind == "manga" else None)

    async def fake_edit_existing_image(prompt, source_image_path, generated_output_path, *, mask_bytes=None, api_key=None, size=None):
        assert prompt == "prompt"
        assert source_image_path == local_source
        assert generated_output_path == output_path
        assert api_key == "img-key"
        return oss_url

    monkeypatch.setattr(main, "edit_existing_image", fake_edit_existing_image)

    result = _run(main.adjust_story_cover(114, request, db))

    assert story.cover_image == oss_url
    assert result == {"cover_image": oss_url, "prompt": "prompt"}
    assert db.committed is True
    assert db.refreshed == [story]
