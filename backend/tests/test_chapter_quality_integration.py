import pytest

from services import deepseek


@pytest.mark.asyncio
async def test_repair_chapter_opening_only_preserves_body(monkeypatch):
    original = "旧开头没有承接。" + "后续正文不应该被重写。" * 120
    repaired_opening = "林墨推开门，看见上一章倒下的人影还在门槛边。"

    async def fake_post(*args, **kwargs):
        class Response:
            def raise_for_status(self):
                return None

            @property
            def text(self):
                return "{}"

        return Response()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return await fake_post()

    monkeypatch.setattr(deepseek.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(deepseek, "_deepseek_auth_headers", lambda api_key=None: {})
    monkeypatch.setattr(
        deepseek,
        "_response_json",
        lambda resp, context="DeepSeek": {"choices": [{"message": {"content": repaired_opening}}]},
    )

    result = await deepseek.repair_chapter_opening_only(
        content=original,
        previous_handoff={"ending_location": "门槛", "active_conflict": "倒下的人影"},
        story_context={},
        chapter_info={"chapter_number": 2},
        api_key="test",
        system_prompt="system",
    )

    assert result.startswith(repaired_opening)
    assert "后续正文不应该被重写" in result
