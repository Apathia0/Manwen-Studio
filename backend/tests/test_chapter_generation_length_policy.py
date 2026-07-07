import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


class _FakeResponse:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self._content = content
        self._finish_reason = finish_reason

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [
                {
                    "finish_reason": self._finish_reason,
                    "message": {"content": self._content},
                }
            ]
        }


def _run(coro):
    return asyncio.run(coro)


def test_length_policy_constants_are_aligned():
    deepseek_text = (BACKEND_DIR / "services" / "deepseek.py").read_text(encoding="utf-8")
    main_text = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
    prompt_template_text = (BACKEND_DIR / "services" / "prompt_template.py").read_text(encoding="utf-8")
    frontend_text = (PROJECT_DIR / "frontend" / "src" / "prompts" / "inkai-chapter.ts").read_text(encoding="utf-8")
    calibrate_text = (BACKEND_DIR / "scripts" / "calibrate_max_tokens.py").read_text(encoding="utf-8")

    assert "CHAPTER_TARGET_MIN_CHARS = 2200" in deepseek_text
    assert "CHAPTER_TARGET_MAX_CHARS = 2800" in deepseek_text
    assert "CHAPTER_TARGET_IDEAL_CHARS = 2500" in deepseek_text
    assert "CHAPTER_FIRST_PASS_MIN_CHARS = 2350" in deepseek_text
    assert "CHAPTER_FIRST_PASS_MAX_CHARS = 2650" in deepseek_text
    assert "CHAPTER_COMPLETION_MAX_TOKENS = 3328" in deepseek_text
    assert "CHAPTER_SOFT_MAX_CHARS" not in deepseek_text
    assert "CHAR_RETRY_LIMIT" not in deepseek_text
    assert "if _char_count > CHAR_RETRY_LIMIT" not in deepseek_text
    assert "已保留完整正文不做截断" not in deepseek_text
    assert '"max_tokens": 3328' not in deepseek_text

    assert "'标准章节': { min: 2200, max: 2800, ideal: 2500 }" in frontend_text
    assert "TARGET_CHARS = (2200, 2800)" in calibrate_text
    assert "RECOMMENDED_MAX_TOKENS = 3328" in calibrate_text
    assert "10-12 段结构" in calibrate_text

    assert "REFERENCE_CHAPTER_PROMPT_SEED" in main_text
    assert "标准章节必须控制在 2200-2800 字，理想约 2500 字" in main_text
    assert '"prompt.chapter_generation": NOVEL_PROMPT_SEED' in main_text
    assert '"prompt.reference_chapter": REFERENCE_CHAPTER_PROMPT_SEED' in main_text

    assert "CHAPTER_CUSTOM_STYLE_MAX_CHARS = 16000" in prompt_template_text
    assert "超过2000字符限制" not in prompt_template_text


def test_chapter_template_custom_notes_are_not_cut_at_2000_chars():
    from services.prompt_template import build_prompt_from_params

    prefix = "篇幅要求：标准章节两千五百字左右，必须完整展开。"
    filler = "承接前文人物状态，补足冲突铺垫、角色反应、关键对话。"
    tail = "尾部约束：章末钩子自然，禁止AI味，不能输出梗概。"
    custom = prefix + filler * 120 + tail

    assert len(custom) > 2000

    prompt = build_prompt_from_params(
        "基础提示词",
        {"custom_style_notes": custom},
        "chapter",
    )

    assert prefix in prompt
    assert tail in prompt
    assert "已截断，超过2000字符限制" not in prompt


def test_expand_chapter_rewrites_when_text_exceeds_standard(monkeypatch):
    import services.deepseek as ds

    calls: list[dict] = []
    responses = ["长" * 3100, "准" * 2500]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            calls.append(json)
            return _FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(ds.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(ds, "DEEPSEEK_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(ds, "DEEPSEEK_MODEL", "deepseek-chat")

    content = _run(ds.expand_chapter_to_content({"title": "测试故事"}, {"chapter_number": 1}, api_key="sk-test"))

    assert content == "准" * 2500
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == ds.CHAPTER_COMPLETION_MAX_TOKENS
    assert "10-12 个自然段" in calls[0]["messages"][1]["content"]
    retry_prompt = calls[1]["messages"][1]["content"]
    assert "正文超过标准" in retry_prompt
    assert "禁止直接截断" in retry_prompt
    assert "保留开篇钩子、核心冲突、关键因果" in retry_prompt


def test_expand_chapter_retries_when_text_is_too_short(monkeypatch):
    import services.deepseek as ds

    calls: list[dict] = []
    responses = ["短" * 1800, "足" * 2300]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            calls.append(json)
            return _FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(ds.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(ds, "DEEPSEEK_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(ds, "DEEPSEEK_MODEL", "deepseek-chat")

    content = _run(ds.expand_chapter_to_content({"title": "测试故事"}, {"chapter_number": 1}, api_key="sk-test"))

    assert content == "足" * 2300
    assert len(calls) == 2
    assert "正文展开不足" in calls[1]["messages"][1]["content"]
