"""AI 驱动章节创作包（正文创作说明）测试。

覆盖：
- render_ai_creation_pack：AI JSON → markdown 渲染契约（# 标题 / ## 分区 / - 字段 / 1. 编号）
- _normalize_brief：字段级兜底，缺失时渲染不崩溃
- _compact_sections：超出输入上限时按优先级裁剪
- generate_ai_creation_brief：AI 调用失败返回 None（触发调用方回退固定模板）
"""

import asyncio
import json as _json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.chapter_creation_pack import (
    CREATION_PACK_RENDER_VERSION,
    render_ai_creation_pack,
    render_creation_pack,
)
from services.creation_pack_ai import (
    MAX_INPUT_CHARS,
    _call_creation_pack_ai,
    _compact_sections,
    _normalize_brief,
    generate_ai_creation_brief,
)


def _brief() -> dict:
    """构造一份完整的 AI 创作说明样本。"""
    return {
        "chapter_task": {
            "goal": "取得残卷并确认其价值",
            "conflict": "拍卖行与神秘势力的争夺",
            "payoff": "残卷第一页内容揭晓",
            "ending_hook": "灰市方向传来异响",
        },
        "plot_beats": [
            {
                "order": 1,
                "type": "开篇钩子",
                "summary": "陈玄在拍卖行门口被拦下",
                "characters": ["陈玄", "拍卖行管事"],
                "key_actions": ["亮出请柬", "试探口风"],
                "dialogue_hints": "管事话里带刺",
            }
        ],
        "foreshadowing": [
            {
                "title": "残卷来源",
                "status": "approaching",
                "action": "推进",
                "note": "通过拍卖行底册暗示残卷出自灰市",
            }
        ],
        "characters": [
            {
                "name": "陈玄",
                "motivation": "确认残卷真伪",
                "current_state": "持有请柬，初到拍卖行",
                "arc": "从谨慎观望到主动试探",
            }
        ],
        "scenes": [
            {
                "location": "拍卖行大厅",
                "atmosphere": "压抑而暗流涌动",
                "key_details": "穹顶灯、侍者托盘、角落盯梢者",
            }
        ],
        "continuity": {
            "must_keep": ["陈玄持有请柬", "残卷尚未公开"],
            "avoid": ["不得提前公开残卷内容", "不得让主角在此章离城"],
            "boundary_notes": "本章仅推进到残卷内容揭晓前一刻",
        },
        "writing_guide": {
            "dialogue": "对话口语化，避免书面腔",
            "emotion": "以动作与细节展示情绪，禁止直写",
            "style": "网文快节奏，章末留钩",
            "quality_rules": ["禁止使用破折号", "禁止情绪词直写"],
        },
    }


def _context_pack() -> dict:
    return {"sections": {"chapter_plan": "第1章计划", "facts": ["残卷在陈玄手中"]}, "source": "knowledge"}


def test_ai_render_contains_title_and_sections():
    rendered = render_ai_creation_pack(_brief(), _context_pack())
    assert rendered.startswith("# 第1章创作包")
    for section_label in ("本章任务", "剧情推进", "伏笔管理", "人物动机与状态", "场景设定", "连续性约束", "写作要点"):
        assert f"## {section_label}" in rendered


def test_ai_render_formats_fields_and_numbering():
    rendered = render_ai_creation_pack(_brief(), _context_pack())
    assert "## 本章任务" in rendered
    assert "- 本章目标：取得残卷并确认其价值" in rendered
    assert "- 核心冲突：拍卖行与神秘势力的争夺" in rendered
    assert "- 章末钩子：灰市方向传来异响" in rendered
    assert "## 剧情推进" in rendered
    assert "- 节拍概述：陈玄在拍卖行门口被拦下" in rendered
    assert "1. 陈玄" in rendered
    assert "## 伏笔管理" in rendered
    assert "- 伏笔标题：残卷来源" in rendered
    assert "- 状态：临近回收" in rendered


def test_ai_render_normalizes_missing_fields():
    rendered = render_ai_creation_pack({"chapter_task": {"goal": "取得残卷"}}, _context_pack())
    assert "## 本章任务" in rendered
    assert "- 本章目标：取得残卷" in rendered
    assert "## 剧情推进" not in rendered


def test_ai_render_hides_private_keys():
    brief = _brief()
    brief["_private"] = "不应出现"
    rendered = render_ai_creation_pack(brief, _context_pack())
    assert "不应出现" not in rendered


def test_normalize_brief_keeps_full_brief():
    brief = _brief()
    normalized = _normalize_brief(brief)
    assert normalized["chapter_task"]["goal"] == "取得残卷并确认其价值"
    assert normalized["foreshadowing"][0]["status"] == "approaching"


def test_normalize_brief_fills_unknown_keys():
    normalized = _normalize_brief({"chapter_task": {"goal": "目标"}})
    assert normalized["chapter_task"]["goal"] == "目标"
    assert "conflict" not in normalized["chapter_task"]
    assert normalized["plot_beats"] == []
    assert normalized["characters"] == []
    assert normalized["scenes"] == []
    assert normalized["continuity"]["must_keep"] == []
    assert normalized["writing_guide"]["quality_rules"] == []

def test_compact_sections_drops_low_priority_sections():
    sections = {
        "chapter_plan": "x" * 200,
        "previous_chapter": "x" * 200,
        "open_threads": "x" * 200,
        "facts": "x" * 200,
        "low_value_section": "y" * 100,
    }
    compacted = _compact_sections(sections, max_chars=500)
    assert "chapter_plan" in compacted
    assert "previous_chapter" in compacted
    assert "low_value_section" not in compacted
    assert sum(len(str(v)) for v in compacted.values()) <= 500


def test_compact_sections_empty_input():
    assert _compact_sections({}, max_chars=100) == {}
    assert _compact_sections(None, max_chars=100) == {}


def test_generate_brief_returns_none_when_ai_fails(monkeypatch):
    async def fake_call(*args, **kwargs):
        raise RuntimeError("网络中断")
    monkeypatch.setattr("services.creation_pack_ai._call_creation_pack_ai", fake_call)
    brief = asyncio.run(generate_ai_creation_brief(_context_pack(), {"chapter_number": 1}, api_key="test-key"))
    assert brief is None


def test_generate_brief_returns_none_without_api_key(monkeypatch):
    async def fake_call(*args, **kwargs):
        raise AssertionError("无 api_key 时不应发起 AI 调用")
    monkeypatch.setattr("services.creation_pack_ai._call_creation_pack_ai", fake_call)
    brief = asyncio.run(generate_ai_creation_brief(_context_pack(), {"chapter_number": 1}, api_key=None))
    assert brief is None


def test_generate_brief_parses_valid_ai_output(monkeypatch):
    async def fake_call(*args, **kwargs):
        return _brief()
    monkeypatch.setattr("services.creation_pack_ai._call_creation_pack_ai", fake_call)
    brief = asyncio.run(generate_ai_creation_brief(_context_pack(), {"chapter_number": 1}, api_key="test-key"))
    assert brief is not None
    assert brief["chapter_task"]["goal"] == "取得残卷并确认其价值"


def test_call_ai_uses_json_object_response_format():
    """确认 payload 使用 response_format json_object（与知识库 AI 同步一致）。"""
    captured = {}

    async def fake_post(url, *, json=None, timeout=None, **kwargs):
        captured["payload"] = json
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [{"message": {"content": _json.dumps(_brief(), ensure_ascii=False)}}]
            },
        )

    class FakeClient:
        async def __aenter__(self):
            return SimpleNamespace(post=fake_post)

        async def __aexit__(self, *exc):
            return False

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("services.creation_pack_ai.httpx.AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr("services.creation_pack_ai._deepseek.runtime_base_url", lambda: "https://api.test/v1")
    monkeypatch.setattr("services.creation_pack_ai._deepseek.runtime_model", lambda: "deepseek-chat")

    result = asyncio.run(_call_creation_pack_ai("test-key", "system", "user"))
    assert result is not None
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    # 思考型模型 reasoning 可吃掉 8K+ 输出预算，初始预算应已放大
    assert captured["payload"]["max_tokens"] == 16384
    monkeypatch.undo()


def test_call_ai_boosts_max_tokens_when_reasoning_ate_budget():
    """思考吃光输出预算（HTTP 200 + 空 content + finish_reason=length）时升级 max_tokens 重试。"""
    captured_payloads = []

    async def fake_post(url, *, json=None, timeout=None, **kwargs):
        captured_payloads.append(json)
        if len(captured_payloads) == 1:
            usage = {
                "completion_tokens": 8192,
                "completion_tokens_details": {"reasoning_tokens": 8116},
            }
            message = {"content": "", "reasoning_content": "思考" * 200}
            finish_reason = "length"
        else:
            usage = {}
            message = {"content": _json.dumps(_brief(), ensure_ascii=False)}
            finish_reason = "stop"
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": message, "finish_reason": finish_reason}], "usage": usage},
        )

    class FakeClient:
        async def __aenter__(self):
            return SimpleNamespace(post=fake_post)

        async def __aexit__(self, *exc):
            return False

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("services.creation_pack_ai.httpx.AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr("services.creation_pack_ai._deepseek.runtime_base_url", lambda: "https://api.test/v1")
    monkeypatch.setattr("services.creation_pack_ai._deepseek.runtime_model", lambda: "glm-5.3-flash")

    result = asyncio.run(_call_creation_pack_ai("test-key", "system", "user"))
    assert result is not None
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["max_tokens"] == 16384
    assert captured_payloads[1]["max_tokens"] == 32768
    monkeypatch.undo()


def test_call_ai_does_not_boost_on_non_length_empty_content():
    """finish_reason=stop 的空 content 不属于思考吃预算，不升级预算，直接失败回退模板。"""
    calls = []

    async def fake_post(url, *, json=None, timeout=None, **kwargs):
        calls.append(json)
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
        )

    class FakeClient:
        async def __aenter__(self):
            return SimpleNamespace(post=fake_post)

        async def __aexit__(self, *exc):
            return False

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("services.creation_pack_ai.httpx.AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr("services.creation_pack_ai._deepseek.runtime_base_url", lambda: "https://api.test/v1")
    monkeypatch.setattr("services.creation_pack_ai._deepseek.runtime_model", lambda: "glm-5.3-flash")

    with pytest.raises(RuntimeError, match="连续 2 次失败"):
        asyncio.run(_call_creation_pack_ai("test-key", "system", "user"))
    # 非 length 空正文走普通重试：第二次 attempt 预算按档位计算仍为 16384（无思考升级）
    assert [call["max_tokens"] for call in calls] == [16384, 16384]
    monkeypatch.undo()


import json
from types import SimpleNamespace


def test_render_version_bumped_to_7():
    assert CREATION_PACK_RENDER_VERSION >= 7


def test_ai_render_keeps_same_section_style_as_template():
    """AI 渲染与模板渲染共用相同 markdown 排版契约（# / ## / - / 1.）。"""
    ai_rendered = render_ai_creation_pack(_brief(), _context_pack())
    template_rendered = render_creation_pack(_context_pack())
    for line in template_rendered.splitlines():
        if line.startswith("# "):
            assert ai_rendered.splitlines()[0].startswith("# ")
            break
    assert "## " in ai_rendered


def test_ai_render_appends_deterministic_continuity_sections():
    """AI 版创作包只确定性追加精简的上一章衔接三要素（不依赖 AI 提炼，不注入冗余记忆）。"""
    context_pack = {
        "sections": {
            "chapter_plan": "第1章计划",
            "story_memory": {"story_state": "陈玄已取得残卷，身处灰市", "open_loops": ["拍卖行势力仍在追踪"]},
            "previous_chapter": {
                "chapter_handoff": {
                    "opening_must_continue": "陈玄带队向野地道口方向行进",
                    "ending_location": "秘境外的野地，暮色已深",
                    "active_conflict": "楚家截杀失败后可能派后续人员",
                }
            },
            "recent_chapters": [{"chapter_number": 1, "title": "残卷", "summary": "陈玄取得残卷"}],
        },
        "source": "knowledge",
    }
    rendered = render_ai_creation_pack(_brief(), context_pack)
    assert "## 上一章强制衔接" in rendered
    assert "- 上一章必须承接：陈玄带队向野地道口方向行进" in rendered
    assert "- 当前开场位置：秘境外的野地" in rendered
    assert "- 即时冲突：楚家截杀失败后可能派后续人员" in rendered
    assert "## 故事记忆" not in rendered
    assert "## 前文章节" not in rendered


def test_ai_render_skips_empty_continuity_sections():
    """AI 版创作包在 sections 缺失或上一章手递接为空时保持现有 7 分区输出，不追加空区块。"""
    rendered = render_ai_creation_pack(_brief(), {"sections": {}, "source": "knowledge"})
    assert "## 上一章强制衔接" not in rendered
    assert "## 本章任务" in rendered


def test_ai_render_skips_empty_handoff_fields():
    """上一章手递接字段全部为空时，不追加衔接区块。"""
    context_pack = {
        "sections": {"previous_chapter": {"chapter_handoff": {"opening_must_continue": "", "ending_location": "", "active_conflict": ""}}},
        "source": "knowledge",
    }
    rendered = render_ai_creation_pack(_brief(), context_pack)
    assert "## 上一章强制衔接" not in rendered


def test_ai_render_handoff_without_nested_key():
    """sections 中 previous_chapter 无 chapter_handoff 键时安全跳过，不崩溃。"""
    context_pack = {"sections": {"previous_chapter": {"summary_text": "仅摘要，无手递接"}}, "source": "knowledge"}
    rendered = render_ai_creation_pack(_brief(), context_pack)
    assert "## 上一章强制衔接" not in rendered
    assert "## 本章任务" in rendered
