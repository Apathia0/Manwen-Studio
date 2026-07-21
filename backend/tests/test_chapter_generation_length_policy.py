import asyncio
import hashlib
import sys
from pathlib import Path

import pytest


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
    assert "CHAPTER_FIRST_PASS_MIN_CHARS = 2300" in deepseek_text
    assert "CHAPTER_FIRST_PASS_MAX_CHARS = 2550" in deepseek_text
    assert "CHAPTER_COMPLETION_MAX_TOKENS = 2816" in deepseek_text
    assert "CHAPTER_SOFT_MAX_CHARS" not in deepseek_text
    assert "CHAR_RETRY_LIMIT" not in deepseek_text
    assert "if _char_count > CHAR_RETRY_LIMIT" not in deepseek_text
    assert "已保留完整正文不做截断" not in deepseek_text
    assert '"max_tokens": 3328' not in deepseek_text

    assert "'标准章节': { min: 2200, max: 2800, ideal: 2500 }" in frontend_text
    assert "TARGET_CHARS = (2200, 2800)" in calibrate_text
    assert "RECOMMENDED_MAX_TOKENS = 2816" in calibrate_text
    assert "9-10 段结构" in calibrate_text

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


def test_expand_chapter_prefers_multi_agent_pipeline(monkeypatch):
    import services.deepseek as ds
    import services.chapter_agents as ca

    calls: list[dict] = []

    async def fake_pipeline(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "content": "新" * 2500,
            "review": {"approved": True, "overall_score": 92},
            "creation_pack": {"writer_brief": "测试"},
        }

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fake_pipeline)

    content = _run(ds.expand_chapter_to_content({"title": "测试故事"}, {"chapter_number": 1}, api_key="sk-test"))

    assert content == "新" * 2500
    assert len(calls) == 1
    assert calls[0]["max_revisions"] == 3
    assert calls[0]["chapter_info"]["chapter_number"] == 1


def test_expand_chapter_rejects_failed_multi_agent_candidate(monkeypatch):
    import services.deepseek as ds
    import services.chapter_agents as ca

    async def failed_pipeline(**kwargs):
        return {
            "ok": False,
            "content": "未达标正文" * 300,
            "review": {"approved": False, "overall_score": 60, "findings": ["缺少回报结算"]},
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 3,
            "finish_reason": "length",
        }

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", failed_pipeline)
    story_context = {"title": "测试故事"}

    with pytest.raises(ds.ChapterPipelineQualityError):
        _run(ds.expand_chapter_to_content(story_context, {"chapter_number": 1}, api_key="sk-test"))

    cached = story_context["_last_chapter_pipeline_result"]
    assert cached["ok"] is False
    assert cached["review"]["overall_score"] == 60
    assert cached["finish_reason"] == "length"


def test_expand_chapter_rewrites_when_text_exceeds_standard(monkeypatch):
    import services.deepseek as ds
    import services.chapter_agents as ca

    async def force_legacy_pipeline(**kwargs):
        raise RuntimeError("force legacy fallback")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", force_legacy_pipeline)

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
    assert "9-10 个自然段" in calls[0]["messages"][1]["content"]
    retry_prompt = calls[1]["messages"][1]["content"]
    assert "正文超过标准" in retry_prompt
    assert "禁止直接截断" in retry_prompt
    assert "保留开篇钩子、核心冲突、关键因果" in retry_prompt


def test_expand_chapter_retries_when_text_is_too_short(monkeypatch):
    import services.deepseek as ds
    import services.chapter_agents as ca

    async def force_legacy_pipeline(**kwargs):
        raise RuntimeError("force legacy fallback")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", force_legacy_pipeline)

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


def test_expand_chapter_treats_finish_reason_length_as_rewrite(monkeypatch):
    import services.deepseek as ds
    import services.chapter_agents as ca

    async def force_legacy_pipeline(**kwargs):
        raise RuntimeError("force legacy fallback")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", force_legacy_pipeline)

    calls: list[dict] = []
    responses = [("截" * 2500, "length"), ("整" * 2450, "stop")]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            calls.append(json)
            content, finish_reason = responses[len(calls) - 1]
            return _FakeResponse(content, finish_reason=finish_reason)

    monkeypatch.setattr(ds.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(ds, "DEEPSEEK_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(ds, "DEEPSEEK_MODEL", "deepseek-chat")

    content = _run(ds.expand_chapter_to_content({"title": "测试故事"}, {"chapter_number": 1}, api_key="sk-test"))

    assert content == "整" * 2450
    assert len(calls) == 2
    assert "正文超过标准" in calls[1]["messages"][1]["content"]


def test_expand_chapter_does_not_fallback_to_invalid_overlong_candidate(monkeypatch):
    import services.deepseek as ds
    import services.chapter_agents as ca

    async def force_legacy_pipeline(**kwargs):
        raise RuntimeError("force legacy fallback")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", force_legacy_pipeline)

    calls: list[dict] = []
    responses = ["长" * 3100, "更长" * 1050, "最长" * 1100]

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

    assert content == "最长" * 1100
    assert len(calls) == 3


def test_creation_pack_boundary_filters_current_chapter_generic_terms():
    import services.chapter_agents as ca

    chapter_scope = {
        "current_chapter_card": {
            "title": "异兽初猎，技术制胜",
            "summary": "陈玄尝试猎杀獠牙野猪，采集精血和兽骨。",
        },
        "future_chapters_for_boundary_only": [
            {"chapter_number": 7, "title": "黑吃黑局，隐忍布局"},
            {"chapter_number": 8, "title": "交易变现，资源闭环"},
        ],
    }
    pack = {
        "chapter_task": chapter_scope["current_chapter_card"],
        "plot_beats": [
            "陈玄完成异兽猎杀并采集精血和兽骨。",
            "他计划明日前去黑市变现。",
        ],
        "ending_hook": "明天还有更长的路要走，他准备去黑市交易。",
        "do_not_write": [],
    }

    cleaned = ca._sanitize_creation_pack_boundary(pack, chapter_scope)

    assert "异兽猎杀" not in cleaned.get("future_boundary_terms", [])
    assert "异兽分布" not in cleaned.get("future_boundary_terms", [])
    assert "黑吃黑" in cleaned.get("future_boundary_terms", [])
    assert "交易变现" in cleaned.get("future_boundary_terms", [])
    assert cleaned["ending_hook"] == ca._NEUTRAL_ENDING_HOOK
    assert all("黑市" not in item for item in cleaned["plot_beats"])
    assert "future_drift" not in cleaned.get("future_boundary_terms", [])


def test_future_boundary_terms_ignore_current_scope_variants():
    import services.chapter_agents as ca

    current_text = "肉身经过灵草滋养初具基础后，陈玄开始尝试猎杀秘境低级异兽，完成精血和兽骨采集。"

    assert ca._term_matches_current_scope_variant("异兽猎杀", current_text) is True
    assert ca._is_useful_future_boundary_term("异兽猎杀", current_text) is False
    assert ca._is_useful_future_boundary_term("黑市交易", current_text) is True
    assert ca._is_useful_future_boundary_term("交易变现", current_text) is True


def test_creation_pack_boundary_filters_future_drift_without_terms():
    import services.chapter_agents as ca

    chapter_scope = {
        "current_chapter_card": {
            "title": "异兽初猎，技术制胜",
            "summary": "陈玄尝试猎杀獠牙野猪，采集精血和兽骨。",
        },
        "future_chapters_for_boundary_only": [],
    }
    pack = {
        "chapter_task": chapter_scope["current_chapter_card"],
        "plot_beats": [
            "陈玄完成异兽猎杀并采集精血和兽骨。",
            "他计划明日前去黑市变现。",
        ],
        "ending_hook": "明天去黑市交易前，他把材料重新打包。",
        "do_not_write": [],
    }

    cleaned = ca._sanitize_creation_pack_boundary(pack, chapter_scope)

    assert cleaned["ending_hook"] == ca._NEUTRAL_ENDING_HOOK
    assert all("黑市" not in item for item in cleaned["plot_beats"])
    assert all("变现" not in item for item in cleaned["plot_beats"])
    assert "future_drift" not in cleaned.get("future_boundary_terms", [])


def test_normalize_plot_beats_keeps_closure_while_capping_density():
    import services.chapter_agents as ca

    pack = {
        "chapter_task": {"goal": "完成第一次异兽狩猎并获得材料"},
        "plot_beats": [
            "陈玄确认风向",
            "他检查短刀",
            "他观察獠牙野猪",
            "他试探异兽反应",
            "他布置诱饵",
            "第一次攻击失败",
            "他调整步法",
            "核心冲突爆发",
            "他利用制胜动作结束胜负",
            "采集精血和兽骨",
            "清点收获和身体代价",
            "章尾停在当前事件余波",
        ],
    }

    normalized = ca._normalize_plot_beats(pack)
    beats = normalized["plot_beats"]

    assert ca.PLOT_BEATS_MIN <= len(beats) <= ca.PLOT_BEATS_MAX
    assert any("胜负" in item or "制胜" in item or "核心冲突" in item for item in beats)
    assert any("结算" in item or "采集" in item or "清点" in item for item in beats)
    assert any("余波" in item or "章尾" in item for item in beats)


def test_sanitize_editor_feedback_drops_future_drift_but_keeps_negative_boundary_rules():
    import services.chapter_agents as ca

    creation_pack = {
        "future_boundary_terms": ["黑市", "交易变现"],
        "chapter_boundary": {"future_chapters_for_boundary_only": [{"title": "交易变现，资源闭环"}]},
    }
    feedback = [
        "建议安排明日去黑市估价变现，作为下章钩子。",
        "删除黑市交易相关内容，保留当前章节材料清点。",
        "压缩观察段，补完整材料清点和身体代价。",
    ]

    cleaned = ca._sanitize_editor_feedback(feedback, creation_pack)

    assert not any("建议安排明日去黑市" in item for item in cleaned)
    assert any("忽略任何要求把后续章节" in item for item in cleaned)
    assert any("删除黑市交易相关内容" in item for item in cleaned)
    assert any("补完整材料清点" in item for item in cleaned)


def test_creation_pack_source_digest_limits_input_and_keeps_current_scope():
    import services.chapter_agents as ca

    story_context = {
        "id": 12,
        "title": "测试故事",
        "story_memory": "连续性记忆：" + "陈玄已完成凝血草炼体。" * 200,
        "story_bible": "圣经摘要：" + "异兽精血可辅助淬体，但有污染风险。" * 160,
        "outline": "大纲：" + "当前卷围绕荒野生存和资源闭环推进。" * 200,
        "characters": [{"name": "陈玄", "state": "冷静、谨慎、刚完成第一次体质强化"}] * 80,
        "reference_takeaways": "拆书引用：" + "冲突前置、回报后置、章尾留当前压力。" * 120,
    }
    chapter_scope = {
        "current_chapter_card": {
            "chapter_number": 6,
            "title": "异兽初猎，技术制胜",
            "summary": "陈玄观察獠牙野猪，用技术完成猎杀并采集精血兽骨。",
        },
        "previous_chapters_for_continuity": [
            {"chapter_number": 1, "summary": "旧信息"},
            {"chapter_number": 2, "summary": "旧信息"},
            {"chapter_number": 3, "summary": "陈玄获得线索"},
            {"chapter_number": 4, "summary": "陈玄准备工具"},
            {"chapter_number": 5, "summary": "陈玄完成炼体"},
        ],
        "future_chapters_for_boundary_only": [
            {"chapter_number": 7, "title": "黑吃黑局，隐忍布局"},
            {"chapter_number": 8, "title": "交易变现，资源闭环"},
            {"chapter_number": 9, "title": "入口坐标，荒野深处"},
            {"chapter_number": 10, "title": "遗迹探索，初见地图"},
            {"chapter_number": 11, "title": "突破小境界"},
            {"chapter_number": 12, "title": "更远后续"},
        ],
    }

    digest, budget = ca._build_creation_pack_source_digest(
        story_context=story_context,
        chapter_info={"chapter_number": 6, "title": "异兽初猎，技术制胜"},
        previous_chapter_summary="第五章余波：" + "药力平稳。" * 80,
        chapter_scope=chapter_scope,
        system_rules="系统规则：" + "只写当前章节，禁止提前写后续。" * 160,
    )

    assert "story_meta" in digest
    assert "current_chapter_card" in digest
    assert "future_chapters_for_boundary_only" in digest
    assert budget["system_rules_digest"] <= 1208
    assert budget["reference_takeaways_source"] <= 1008
    assert budget["outline_or_plan"] <= 1808
    assert budget["total"] < 14000
    assert "第5章" not in digest["previous_chapters_for_continuity"]
    assert "黑吃黑局" in digest["future_chapters_for_boundary_only"]
    assert "更远后续" not in digest["future_chapters_for_boundary_only"]
    assert "伏笔上限" in digest["digest_policy"]


def test_creation_pack_boundary_filters_rules_checklist_and_scene_budget():
    import services.chapter_agents as ca

    chapter_scope = {
        "current_chapter_card": {
            "title": "异兽初猎，技术制胜",
            "summary": "陈玄尝试猎杀獠牙野猪，采集精血和兽骨。",
        },
        "future_chapters_for_boundary_only": [
            {"chapter_number": 7, "title": "黑吃黑局，隐忍布局"},
            {"chapter_number": 8, "title": "交易变现，资源闭环"},
        ],
    }
    pack = {
        "chapter_task": chapter_scope["current_chapter_card"],
        "plot_beats": ["陈玄完成猎杀。", "他计划明日前去黑市变现。"],
        "hard_requirements": ["猎杀獠牙野猪。", "明日前往黑市卖钱。"],
        "closure_requirements": ["采集精血兽骨。", "完成黑市交易变现。"],
        "writer_execution_order": ["先猎杀。", "再进入黑市找到买家。"],
        "missing_if_absent": ["未写黑市交易必须打回。"],
        "writing_rules": ["结尾必须写黑市交易价格。", "字数 2200-2800。"],
        "acceptance_checklist": ["检查是否写出交易变现。", "检查是否完成采集。"],
        "review_focus": ["若未进入黑市则打回。", "检查因果闭环。"],
        "must_keep": ["保留明日前往黑市路线。", "保留精血兽骨。"],
        "reference_takeaways": ["市场价能顶上一阵。", "冲突前置。"],
        "scene_budget": [
            {"scene": "黑市交易", "purpose": "写交易变现", "target_chars": 400, "max_chars": 520},
            {"scene": "采集结算", "purpose": "写当前收获", "target_chars": 450, "max_chars": 540},
        ],
        "do_not_write": [],
    }

    cleaned = ca._sanitize_creation_pack_boundary(pack, chapter_scope)
    joined = "\n".join(
        str(item)
        for field in (
            "plot_beats",
            "hard_requirements",
            "closure_requirements",
            "writer_execution_order",
            "missing_if_absent",
            "writing_rules",
            "acceptance_checklist",
            "review_focus",
            "must_keep",
            "reference_takeaways",
        )
        for item in cleaned.get(field, [])
    )

    assert "黑市" not in joined
    assert "交易变现" not in joined
    assert "市场价" not in joined
    assert "字数 2200-2800" in joined
    assert "检查是否完成采集" in joined
    assert cleaned["scene_budget"][0]["scene"] == "当前事件余波与必要结算"
    assert "不展开后续地点" in cleaned["scene_budget"][0]["purpose"]
    assert "scene_budget" in cleaned["boundary_sanitization"]["fields"]


def test_editor_feedback_filters_future_drift_suggestions():
    import services.chapter_agents as ca

    feedback = [
        "补写返回过程，确认收获，计划明日前去黑市变现。",
        "补一句这些材料按市场价能顶上一阵。",
        "删除明天去黑市这一句，结尾停在当前事件余波。",
        "补全猎杀后的采集动作。",
    ]
    creation_pack = {
        "future_boundary_terms": ["黑市", "交易变现"],
        "chapter_boundary": {},
    }

    cleaned = ca._sanitize_editor_feedback(feedback, creation_pack)

    joined = "\n".join(cleaned)
    assert "计划明日前去黑市变现" not in joined
    assert "市场价" not in joined
    assert "删除明天去黑市这一句" in joined
    assert "补全猎杀后的采集动作" in joined
    assert cleaned[0].startswith("忽略任何要求把后续章节地点")


def test_creation_pack_boundary_filters_market_route_and_relative_time_drift():
    import services.chapter_agents as ca

    chapter_scope = {
        "current_chapter_card": {
            "title": "异兽初猎，技术制胜",
            "summary": "陈玄尝试猎杀獠牙野猪，采集精血和兽骨。",
        },
        "future_chapters_for_boundary_only": [
            {"chapter_number": 8, "title": "交易变现，资源闭环", "summary": "陈玄明早去摊位找买家，按市场行情把材料卖到高价。"},
            {"chapter_number": 9, "title": "秘境深处，寂灭异兆", "summary": "陈玄从西北方向乱石坡找到入口坐标。"},
        ],
    }
    pack = {
        "chapter_task": chapter_scope["current_chapter_card"],
        "plot_beats": [
            "陈玄完成当前猎杀并采集精血兽骨。",
            "他估算市场价，打算明早去摊位找买家卖到好价。",
            "他记下西北方向乱石坡的入口坐标。",
        ],
        "reference_takeaways": ["材料来钱快，能换成现金顶上一阵。"],
        "ending_hook": "明早去乱石坡之前，他先把兽骨藏好。",
        "do_not_write": [],
    }

    cleaned = ca._sanitize_creation_pack_boundary(pack, chapter_scope)
    joined = "\n".join(
        str(item)
        for field in ("plot_beats", "reference_takeaways")
        for item in cleaned.get(field, [])
    )

    assert "市场价" not in joined
    assert "明早" not in joined
    assert "摊位" not in joined
    assert "买家" not in joined
    assert "乱石坡" not in joined
    assert cleaned["ending_hook"] == ca._NEUTRAL_ENDING_HOOK


def test_revision_feedback_is_empty_for_first_draft():
    import services.chapter_agents as ca

    feedback = ca._revision_feedback_for_writer({}, {}, "")

    assert feedback == []


def test_creation_pack_boundary_filters_implicit_future_utilization():
    import services.chapter_agents as ca

    chapter_scope = {
        "current_chapter_card": {
            "title": "异兽初猎，技术制胜",
            "summary": "陈玄尝试猎杀獠牙野猪，采集精血和兽骨。",
        },
        "future_chapters_for_boundary_only": [],
    }
    pack = {
        "chapter_task": chapter_scope["current_chapter_card"],
        "plot_beats": [
            "陈玄完成当前猎杀并采集精血兽骨。",
            "回到安全区域，检查收获，计划后续利用方式。",
        ],
        "scene_budget": [
            {"scene": "章尾余波与当前钩子", "purpose": "留下对未来行动的暗示", "target_chars": 180, "max_chars": 260},
        ],
        "do_not_write": [],
    }

    cleaned = ca._sanitize_creation_pack_boundary(pack, chapter_scope)
    joined = "\n".join(str(item) for item in cleaned.get("plot_beats", []))

    assert "后续利用" in joined
    assert "计划后续" in joined
    assert cleaned["scene_budget"][0]["scene"] == "章尾余波与当前钩子"
    assert "未来行动" in cleaned["scene_budget"][0]["purpose"]


def test_boundary_tail_local_repair_removes_trade_plan():
    import services.chapter_agents as ca

    content = "陈玄压住左臂伤口，拖着布袋回到安全区域。" + "伤口还在发热。" * 390
    content += "他准备明日去黑市交易，把兽骨变现后再想下一步。"

    repaired, changed, hits = ca._repair_boundary_tail_locally(content)

    assert changed is True
    assert {"黑市", "交易", "变现", "明日", "下一步"} & set(hits)
    assert 2200 <= ca.count_chapter_chars(repaired) <= 2800
    assert not ca._tail_boundary_hits(repaired)
    assert "陈玄把包口扎紧" in repaired


def test_local_safety_treats_future_hook_as_editor_soft_warning():
    import services.chapter_agents as ca

    content = "陈玄把精血封进瓷瓶，兽骨压在布袋底。" + "伤口还在发热。" * 390
    content += "他知道交易变现终究会来，但今晚只能先把命和材料一起带回去。"
    chapter_scope = {
        "current_chapter_card": {"title": "异兽初猎，技术制胜", "summary": "完成狩猎并采集材料。"},
        "future_chapters_for_boundary_only": [
            {"chapter_number": 8, "title": "交易变现，资源闭环"}
        ],
    }

    local = ca._local_safety_review(content, chapter_scope)

    assert local["ok"] is True
    assert local["hard_failures"] == []
    assert any(item["code"] == "boundary.future_event_candidate" for item in local["soft_warnings"])


def test_boundary_tail_repair_only_when_editor_mentions_real_boundary_issue():
    import services.chapter_agents as ca

    soft_review = {
        "findings": ["章尾黑市方向只是轻量伏笔，可以保留。"],
        "rewrite_brief": ["无需返修，仅微调表达。"],
    }
    hard_review = {
        "raw": {"blocking_issues": ["提前兑现后续交易流程，已经写成完整场面。"]},
        "rewrite_brief": ["删除交易流程和价格结算。"],
    }

    assert ca._review_mentions_boundary_issue(soft_review) is False
    assert ca._review_mentions_boundary_issue(hard_review) is True


def test_pipeline_uses_best_candidate_when_later_revision_gets_worse(monkeypatch):
    import services.chapter_agents as ca

    usable = "陈玄压住左臂伤口，拖着布袋回到安全区域。" + "伤口还在发热。" * 390
    worse = "陈玄继续周旋。" * 900
    writes: list[dict] = []

    async def fake_writer(**kwargs):
        writes.append(kwargs)
        if len(writes) == 1:
            return {"content": usable, "finish_reason": "stop"}
        return {"content": worse, "finish_reason": "length"}

    async def fake_editor(**kwargs):
        content = kwargs["content"]
        if content == usable:
            return {
                "approved": False,
                "overall_score": 86,
                "findings": ["可读性达标，仅建议轻微润色。"],
                "rewrite_brief": ["无需返修，主体可用。"],
                "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
            }
        return {
            "approved": False,
            "overall_score": 0,
            "findings": ["正文生成被模型截断。"],
            "rewrite_brief": ["必须重写。"],
            "local_safety": {
                "ok": False,
                "char_count": ca.count_chapter_chars(content),
                "hard_failures": [{"code": "length.too_long", "message": "正文字数超过 2800 字"}],
            },
        }

    monkeypatch.setattr(ca, "write_chapter_from_pack", fake_writer)
    monkeypatch.setattr(ca, "review_chapter_with_editor_agent", fake_editor)

    result = _run(ca.run_chapter_creation_pipeline(
        story_context={"title": "测试故事"},
        chapter_info={"chapter_number": 6, "title": "异兽初猎，技术制胜"},
        api_key="sk-test",
        creation_pack={
            "chapter_task": {"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            "plot_beats": ["猎杀", "采集", "余波"],
            "do_not_write": [],
        },
        max_revisions=2,
    ))

    assert result["ok"] is False
    assert result["content"] == usable
    assert result["best_candidate_source"] == "editor_review"
    assert len(writes) == 2


def test_creation_pack_adds_default_scene_budget():
    import services.chapter_agents as ca

    pack = {
        "chapter_task": {"title": "测试章节"},
        "plot_beats": ["开场", "冲突", "结算"],
    }

    normalized = ca._ensure_scene_budget(pack)
    budget = normalized["scene_budget"]

    assert len(budget) >= 5
    assert sum(item["target_chars"] for item in budget) >= ca.SCENE_BUDGET_IDEAL_TOTAL
    assert budget[0]["scene"] == "开场承接与目标压迫"
    assert any("章尾" in item["scene"] for item in budget)


def test_writer_prompt_includes_scene_budget_and_execution_contract(monkeypatch):
    import services.chapter_agents as ca

    captured: dict[str, str] = {}

    async def fake_chat_completion(**kwargs):
        captured["prompt"] = kwargs["messages"][1]["content"]
        return "正" * 2400, "stop"

    monkeypatch.setattr(ca, "_chat_completion", fake_chat_completion)

    pack = ca._ensure_completion_fields(ca._ensure_scene_budget({
        "chapter_task": {"chapter_number": 6, "title": "异兽初猎，技术制胜"},
        "chapter_boundary": {},
        "plot_beats": ["观察", "交锋", "采集"],
        "hard_requirements": ["猎杀獠牙野猪", "采集精血、獠牙和兽骨"],
        "closure_requirements": ["清理现场并撤离", "返回出租屋清点收获"],
        "missing_if_absent": ["缺少獠牙/兽骨采集必须打回", "缺少返回清点必须打回"],
        "do_not_write": [],
    }))

    result = _run(ca.write_chapter_from_pack(creation_pack=pack, api_key="sk-real"))

    assert result["finish_reason"] == "stop"
    assert "## 场景字数预算" in captured["prompt"]
    assert "开场承接与目标压迫" in captured["prompt"]
    assert "必须给兑现回报、必要结算和章尾余波预留 400-600 字" in captured["prompt"]
    assert "hard_requirements" in captured["prompt"]
    assert "closure_requirements" in captured["prompt"]
    assert "missing_if_absent" in captured["prompt"]
    assert "核心冲突、战斗、交锋或胜负结束不等于章节完成" in captured["prompt"]


def test_length_finish_reason_inside_range_forces_revision_when_editor_not_passed():
    import services.chapter_agents as ca

    content = "陈玄完成当前章的观察、交锋、采集和撤离。" * 120
    review = {
        "approved": False,
        "overall_score": 75,
        "local_safety": {"ok": True},
    }

    force, reason = ca._should_force_length_revision("length", review, content)

    assert ca.LOCAL_MIN_CHARS <= ca.count_chapter_chars(content) <= ca.LOCAL_MAX_CHARS
    assert force is True
    assert reason == "model_length_finish"


def test_pipeline_accepts_editor_pass_even_when_finish_reason_length(monkeypatch):
    import services.chapter_agents as ca

    content = "陈玄完成当前章的观察、交锋、采集和撤离。" * 120
    calls = {"write": 0, "review": 0}

    async def fake_pack(**kwargs):
        return {
            "chapter_task": {"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            "chapter_boundary": {},
            "do_not_write": [],
        }

    async def fake_write(**kwargs):
        calls["write"] += 1
        return {"content": content, "finish_reason": "length"}

    async def fake_review(**kwargs):
        calls["review"] += 1
        return {
            "approved": True,
            "overall_score": 92,
            "rewrite_brief": ["无需修改，直接通过。"],
            "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
        }

    monkeypatch.setattr(ca, "build_chapter_creation_pack", fake_pack)
    monkeypatch.setattr(ca, "write_chapter_from_pack", fake_write)
    monkeypatch.setattr(ca, "review_chapter_with_editor_agent", fake_review)

    result = _run(
        ca.run_chapter_creation_pipeline(
            story_context={"title": "测试故事"},
            chapter_info={"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            api_key="sk-test",
            max_revisions=3,
        )
    )

    assert result["ok"] is True
    assert result["content"] == content
    assert result["attempts"] == 1
    assert result["finish_reason"] == "length"
    assert calls == {"write": 1, "review": 1}


def test_writer_local_sanitize_removes_zero_tolerance_terms():
    import services.chapter_agents as ca

    text = "陈玄深吸一口气，猛地抬头——林中突然传来响动。那一瞬间，在这时，另一个方向，另一个方向传来脚步。"
    cleaned, changes = ca._sanitize_writer_output_locally(text)

    assert "深吸一口气" not in cleaned
    assert "猛地" not in cleaned
    assert "突然" not in cleaned
    assert "瞬间" not in cleaned
    assert "这一这时" not in cleaned
    assert "在这时" not in cleaned
    assert "另一个方向，另一个方向" not in cleaned
    assert "——" not in cleaned
    assert {"深吸一口气，", "猛地", "突然", "一瞬间", "在这时", "另一个方向，另一个方向", "——"}.issubset(set(changes))


def test_writer_revision_uses_safe_budget_for_complete_full_text():
    import services.chapter_agents as ca

    assert ca.WRITER_MAX_TOKENS == 4096
    assert ca._writer_max_tokens(0, False) == 4096
    assert ca._writer_max_tokens(2494, True) == 4096
    assert ca._writer_max_tokens(1800, True) == 4096
    assert ca._writer_max_tokens(3100, True) == 4096


def test_scene_budget_is_tight_enough_for_first_draft():
    import services.chapter_agents as ca

    default_budget = ca._normalize_scene_budget(None)
    assert sum(item["target_chars"] for item in default_budget) == ca.SCENE_BUDGET_IDEAL_TOTAL
    assert max(item["max_chars"] for item in default_budget) <= 1040

    oversized = {
        "scene_budget": [
            {"scene": "开场", "purpose": "铺垫", "target_chars": 500, "max_chars": 680},
            {"scene": "观察", "purpose": "观察", "target_chars": 700, "max_chars": 840},
            {"scene": "冲突", "purpose": "冲突", "target_chars": 1300, "max_chars": 1500},
            {"scene": "结算", "purpose": "结算", "target_chars": 600, "max_chars": 760},
        ]
    }
    normalized = ca._normalize_scene_budget(oversized)

    assert ca.SCENE_BUDGET_IDEAL_TOTAL <= sum(item["target_chars"] for item in normalized) <= ca.SCENE_BUDGET_SOFT_MAX_TOTAL
    assert sum(item["target_chars"] for item in normalized) <= ca.SCENE_BUDGET_SOFT_MAX_TOTAL
    assert all(item["target_chars"] <= item["max_chars"] for item in normalized)


def test_finalize_reuses_cached_pipeline_result(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("终检命中缓存时不应再次远程调用三角色链路")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住石刃。“别动。”母亲看着药碗。“去吧。”他点头。“我会回来。”\n" * 65
    char_count = cq.count_content_chars(content)
    assert 2200 <= char_count <= 2800

    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": True,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": True,
                "overall_score": 95,
                "local_safety": {"ok": True, "char_count": char_count},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 1,
            "finish_reason": "stop",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="unit-test",
        )
    )

    assert result["ok"] is True
    assert result["content"] == content
    assert result["attempts"] == 1
    assert result["report"]["reused_pipeline_result"] is True


def test_editor_hard_pass_allows_missing_local_safety():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    assert ca.LOCAL_MIN_CHARS <= ca.count_chapter_chars(content) <= ca.LOCAL_MAX_CHARS

    review = {"approved": True, "overall_score": 92}

    assert ca._review_is_hard_pass(review, content) is True


def test_editor_hard_pass_rejects_high_score_with_real_blocking_issue():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    review = ca._normalize_review({
        "approved": True,
        "overall_score": 92,
        "blocking_issues": ["剧情逻辑矛盾，必须重写结算段。"],
    })

    assert review["approved"] is False
    assert review["overall_score"] == 92
    assert ca._review_is_hard_pass(review, content) is False


def test_fragment_revision_rejects_shrunken_full_draft():
    import services.chapter_agents as ca

    previous = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    fragment = "陈玄把瓶口拧紧，听见门外有人走过。他没有抬头，只把兽骨压进布袋。" * 12

    assert ca.LOCAL_MIN_CHARS <= ca.count_chapter_chars(previous) <= ca.LOCAL_MAX_CHARS
    assert ca._looks_like_fragment_revision(previous, fragment, True) is True


def test_pipeline_rejects_last_valid_score_below_editor_pass(monkeypatch):
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    calls = {"write": 0, "review": 0}

    async def fake_pack(**kwargs):
        return {
            "chapter_task": {"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            "chapter_boundary": {},
            "do_not_write": [],
        }

    async def fake_write(**kwargs):
        calls["write"] += 1
        return {"content": content, "finish_reason": "length"}

    async def fake_review(**kwargs):
        calls["review"] += 1
        return {
            "approved": False,
            "overall_score": 75,
            "rewrite_brief": ["只需补齐尾句和轻微润色。"],
            "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
        }

    monkeypatch.setattr(ca, "build_chapter_creation_pack", fake_pack)
    monkeypatch.setattr(ca, "write_chapter_from_pack", fake_write)
    monkeypatch.setattr(ca, "review_chapter_with_editor_agent", fake_review)

    result = _run(
        ca.run_chapter_creation_pipeline(
            story_context={"title": "测试故事"},
            chapter_info={"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            api_key="sk-test",
            max_revisions=1,
        )
    )

    assert result["ok"] is False
    assert "soft_pass" not in result
    assert result["content"] == content
    assert calls == {"write": 1, "review": 1}


def test_pipeline_rejects_approved_but_score_below_editor_pass(monkeypatch):
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    calls = {"write": 0, "review": 0}

    async def fake_pack(**kwargs):
        return {
            "chapter_task": {"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            "chapter_boundary": {},
            "do_not_write": [],
        }

    async def fake_write(**kwargs):
        calls["write"] += 1
        return {"content": content, "finish_reason": "stop"}

    async def fake_review(**kwargs):
        calls["review"] += 1
        return {
            "approved": True,
            "overall_score": 75,
            "rewrite_brief": ["质量尚未达到 90 分，不应通过。"],
            "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
        }

    monkeypatch.setattr(ca, "build_chapter_creation_pack", fake_pack)
    monkeypatch.setattr(ca, "write_chapter_from_pack", fake_write)
    monkeypatch.setattr(ca, "review_chapter_with_editor_agent", fake_review)

    result = _run(
        ca.run_chapter_creation_pipeline(
            story_context={"title": "测试故事"},
            chapter_info={"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            api_key="sk-test",
            max_revisions=1,
        )
    )

    assert result["ok"] is False
    assert result["review"]["approved"] is True
    assert result["review"]["overall_score"] == 75
    assert calls == {"write": 1, "review": 1}


def test_finalize_reuses_below_90_cached_pipeline_without_rerun(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("命中三角色候选缓存后不应再次启动完整 pipeline")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    assert 2200 <= char_count <= 2800
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": False,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": False,
                "overall_score": 76,
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 3,
            "finish_reason": "length",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="unit-test",
        )
    )

    assert result["ok"] is False
    assert result["attempts"] == 3
    assert result["report"]["reused_pipeline_result"] is True
    assert result["report"]["reused_pipeline_reason"] == "score_below_editor_pass"


def test_finalize_rejects_near_pass_cached_pipeline_without_rerun(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("编辑近通过且无硬伤时不应再次启动完整 pipeline")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    assert 2200 <= char_count <= 2800
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": False,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": False,
                "overall_score": 86,
                "raw": {"blocking_issues": []},
                "findings": ["个别句式可微调。"],
                "rewrite_brief": ["无需整章返修，仅保留建议。"],
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 2,
            "finish_reason": "length",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="unit-test",
        )
    )

    assert result["ok"] is False
    assert result["attempts"] == 2
    assert result["report"]["reused_pipeline_result"] is True
    assert result["report"]["reused_pipeline_reason"] == "score_below_editor_pass"


def test_finalize_rejects_cached_pipeline_with_soft_blocking_brief_below_pass_score(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("软建议不应触发三角色 pipeline 重跑")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": False,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": False,
                "overall_score": 87,
                "raw": {"blocking_issues": []},
                "rewrite_brief": ["blocking_issues: 无需返修，仅轻微尾句建议。"],
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 2,
            "finish_reason": "stop",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="unit-test",
        )
    )

    assert result["ok"] is False
    assert result["report"]["reused_pipeline_result"] is True
    assert result["report"]["reused_pipeline_reason"] == "score_below_editor_pass"


def test_finalize_rejects_cached_dialogue_issue_below_pass_score(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("对话数量软指标不应触发三角色 pipeline 重跑")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": False,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": False,
                "overall_score": 86,
                "raw": {"blocking_issues": ["缺少至少3句有效对话。"]},
                "rewrite_brief": ["blocking_issues: 缺少至少3句有效对话。"],
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 2,
            "finish_reason": "stop",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="unit-test",
        )
    )

    assert result["ok"] is False
    assert result["report"]["reused_pipeline_result"] is True
    assert result["report"]["reused_pipeline_reason"] == "score_below_editor_pass"


def test_finalize_rejects_near_pass_cached_pipeline_with_blocking_issue(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("命中三角色缓存后只复用结论，不应再次启动完整 pipeline")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": False,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": False,
                "overall_score": 88,
                "raw": {"blocking_issues": ["剧情任务缺失：未完成采集结算。"]},
                "rewrite_brief": ["blocking_issues: 剧情任务缺失，必须补完整采集结果。"],
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 2,
            "finish_reason": "stop",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="unit-test",
        )
    )

    assert result["ok"] is False
    assert result["report"]["reused_pipeline_result"] is True
    assert result["report"]["reused_pipeline_reason"] == "editor_blocking_issue"


def test_finalize_skips_pipeline_rerun_when_disabled_on_cache_miss(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("主生成链路终检缓存未命中时不应再次启动完整 pipeline")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    assert 2200 <= char_count <= 2800
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": True,
            "content_sha256": hashlib.sha256(("旧稿" + content).encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": True,
                "overall_score": 95,
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 1,
            "finish_reason": "stop",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="expand_chapter",
            allow_pipeline_rerun=False,
        )
    )

    assert result["ok"] is True
    assert result["content"] == content
    assert result["attempts"] == 0
    assert result["report"]["pipeline_rerun_skipped"] is True
    assert result["report"]["cache_miss_reason"] == "hash_mismatch"
    assert result["report"]["review"]["reason"] == "pipeline_rerun_disabled"


def test_finalize_rejects_previous_failed_pipeline_when_rerun_disabled(monkeypatch):
    import services.chapter_agents as ca
    import services.chapter_quality as cq

    async def fail_if_called(**kwargs):
        raise AssertionError("已有失败 pipeline 结论时不应再次启动完整 pipeline")

    monkeypatch.setattr(ca, "run_chapter_creation_pipeline", fail_if_called)

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    char_count = cq.count_content_chars(content)
    assert 2200 <= char_count <= 2800
    story_context = {
        "_last_chapter_pipeline_result": {
            "ok": False,
            "content_sha256": hashlib.sha256(("旧失败稿" + content).encode("utf-8")).hexdigest(),
            "char_count": char_count,
            "review": {
                "approved": False,
                "overall_score": 60,
                "findings": ["缺少材料采集、清理、撤离和清点"],
                "local_safety": {"ok": True, "char_count": char_count, "hard_failures": []},
            },
            "creation_pack": {"writer_brief": "测试"},
            "attempts": 3,
            "finish_reason": "length",
        }
    }

    result = _run(
        cq.finalize_generated_chapter_content(
            content=content,
            story_context=story_context,
            chapter_info={"chapter_number": 6, "title": "测试章节"},
            api_key="sk-test",
            source="expand_chapter",
            allow_pipeline_rerun=False,
        )
    )

    assert result["ok"] is False
    assert result["attempts"] == 3
    assert result["report"]["previous_pipeline_failed"] is True
    assert result["report"]["cache_miss_reason"] == "hash_mismatch"
    assert result["report"]["review"]["reason"] == "previous_pipeline_failed"


def test_creation_pack_summary_and_completion_fields_are_normalized():
    import services.chapter_agents as ca

    pack = {
        "chapter_task": {
            "chapter_number": 6,
            "title": "异兽初猎，技术制胜",
            "goal": "完成第一次异兽狩猎并获得材料",
        },
        "target": {"min": 3000, "ideal": 3200, "max": 3600},
        "completion_contract": {
            "pass_score": 80,
            "target_chars": {"min": 1800, "ideal": 2000, "max": 3200},
        },
        "continuity": ["陈玄已经完成凝血草炼体。"],
        "plot_beats": ["观察异兽痕迹", "利用攻击间隙取胜"],
        "hard_requirements": ["猎杀獠牙野猪", "采集精血、獠牙和兽骨"],
        "closure_requirements": ["清理现场", "返回出租屋清点收获"],
        "missing_if_absent": ["没有采集獠牙/兽骨必须打回", "没有返回清点必须打回"],
        "do_not_write": ["不得提前写黑市交易"],
        "scene_budget": [
            {"scene": "开场承接", "purpose": "承接前文", "target_chars": 300, "max_chars": 380},
            {"scene": "核心冲突", "purpose": "完成狩猎", "target_chars": 1200, "max_chars": 1400},
            {"scene": "回报结算", "purpose": "处理材料", "target_chars": 500, "max_chars": 600},
            {"scene": "章尾余波", "purpose": "停在当前压力", "target_chars": 220, "max_chars": 280},
        ],
        "acceptance_checklist": ["自定义验收项：保留冷静克制的文风。"],
    }

    ca._ensure_completion_fields(pack)
    summary = ca._pack_log_zh_summary(pack)

    assert pack["target"] == {"min": 2200, "ideal": 2400, "max": 2800}
    assert pack["completion_contract"]["pass_score"] == 90
    assert pack["completion_contract"]["target_chars"] == {"min": 2200, "ideal": 2400, "max": 2800}
    assert pack["completion_contract"]["execution_policy"]
    assert pack["hard_requirements"] == ["猎杀獠牙野猪", "采集精血、獠牙和兽骨"]
    assert "清理现场" in pack["closure_requirements"]
    assert pack["writer_execution_order"]
    assert "没有返回清点必须打回" in pack["missing_if_absent"]
    assert 6 <= len(pack["acceptance_checklist"]) <= 10
    assert any("剧情闭环" in item or "核心任务" in item for item in pack["acceptance_checklist"])
    assert any("hard_requirements" in item for item in pack["acceptance_checklist"])
    assert "目标字数" in summary
    assert "2200-2800" in summary["目标字数"]
    assert summary["编辑通过分"] == 90
    assert summary["场景预算总字数"] >= ca.SCENE_BUDGET_IDEAL_TOTAL
    assert summary["硬性动作"]
    assert summary["闭环要求"]
    assert summary["缺失必打回"]
    assert summary["验收清单"]


def test_scene_budget_caps_total_max_chars():
    import services.chapter_agents as ca

    pack = {
        "scene_budget": [
            {"scene": "开场", "purpose": "承接", "target_chars": 300, "max_chars": 420},
            {"scene": "观察", "purpose": "找目标", "target_chars": 500, "max_chars": 620},
            {"scene": "战斗", "purpose": "完成核心冲突", "target_chars": 950, "max_chars": 1150},
            {"scene": "结算", "purpose": "处理收获", "target_chars": 450, "max_chars": 580},
            {"scene": "章尾", "purpose": "余波", "target_chars": 180, "max_chars": 260},
        ]
    }

    budget = ca._normalize_scene_budget(pack)

    assert ca.SCENE_BUDGET_IDEAL_TOTAL <= sum(item["target_chars"] for item in budget) <= ca.SCENE_BUDGET_SOFT_MAX_TOTAL
    assert sum(item["max_chars"] for item in budget) <= ca.SCENE_BUDGET_HARD_MAX_TOTAL
    assert all(item["max_chars"] >= item["target_chars"] for item in budget)


def test_near_pass_review_keeps_original_score_and_remains_unapproved():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    review = {
        "approved": False,
        "overall_score": 86,
        "scores": {"overall": 86},
        "findings": ["可微调个别句式。"],
        "rewrite_brief": ["无需返修，仅保留建议。"],
        "raw": {"blocking_issues": []},
        "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
    }

    promoted = ca._promote_near_pass_review(review, content)

    assert promoted["approved"] is False
    assert promoted["overall_score"] == 86
    assert promoted["scores"]["overall"] == 86
    assert "near_pass_promoted" not in promoted


def test_promote_near_pass_review_keeps_real_blocking_failures():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    review = {
        "approved": False,
        "overall_score": 88,
        "rewrite_brief": ["blocking_issues: 剧情任务缺失，必须补完整狩猎结果。"],
        "raw": {"blocking_issues": ["剧情任务缺失"]},
        "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
    }

    result = ca._promote_near_pass_review(review, content)

    assert result["approved"] is False
    assert result["overall_score"] == 88
    assert "near_pass_promoted" not in result


def test_revision_feedback_keeps_soft_suggestions_below_pass_score():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    review = {
        "approved": False,
        "overall_score": 86,
        "findings": ["可以微调个别句式。"],
        "rewrite_brief": ["rewrite_targets: 微调第一处对话语气。", "无需返修，仅保留建议。"],
        "raw": {"blocking_issues": []},
        "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
    }

    feedback = ca._revision_feedback_for_writer(review, {}, content)

    assert feedback


def test_revision_feedback_requires_revision_below_pass_score_after_dialogue_softening():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    review = {
        "approved": False,
        "overall_score": 86,
        "raw": {"blocking_issues": ["缺少至少3句有效对话。"]},
        "rewrite_brief": ["blocking_issues: 缺少至少3句有效对话。"],
        "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
    }

    feedback = ca._revision_feedback_for_writer(review, {}, content)

    assert feedback


def test_revision_feedback_keeps_soft_blocking_brief_below_pass_score():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 60
    review = {
        "approved": False,
        "overall_score": 87,
        "raw": {"blocking_issues": []},
        "rewrite_brief": ["blocking_issues: 无需返修，仅轻微润色建议。", "rewrite_targets: 可微调尾句。"],
        "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
    }

    feedback = ca._revision_feedback_for_writer(review, {}, content)

    assert feedback


def test_revision_feedback_keeps_blockers_but_filters_future_drift_and_dialogue_quota():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀。母亲看着药碗。她说：别逞强。他点头：我知道。门外有人压低声音：走。" * 45
    review = {
        "approved": False,
        "overall_score": 62,
        "raw": {
            "blocking_issues": ["剧情未完成：缺少解剖采集。"],
            "rewrite_targets": [
                "补写解剖采集精血和兽骨。",
                "补写返回过程，确认收获，计划明日前去黑市变现。",
                "补写至少3句有效对话。",
            ],
            "cut": ["删除明天得去一趟黑市这一句。"],
        },
        "rewrite_brief": [
            "blocking_issues: 剧情未完成：缺少解剖采集。",
            "rewrite_targets: 补写返回过程，确认收获，计划黑市变现。",
            "rewrite_targets: 补写至少3句有效对话。",
        ],
        "local_safety": {"ok": True, "char_count": ca.count_chapter_chars(content), "hard_failures": []},
    }
    creation_pack = {
        "future_boundary_terms": ["黑市", "交易变现"],
        "chapter_boundary": {
            "future_chapters_for_boundary_only": [
                {"chapter_number": 8, "title": "交易变现，资源闭环"}
            ]
        },
    }

    feedback = ca._revision_feedback_for_writer(review, creation_pack, content)
    joined = "\n".join(feedback)

    assert "剧情未完成" in joined
    assert "解剖采集" in joined
    assert "计划明日前去黑市变现" not in joined
    assert "计划黑市变现" not in joined
    assert "至少3句有效对话" not in joined
    assert "删除明天得去一趟黑市" in joined


def test_repair_truncated_tail_locally_when_repaired_text_still_in_range():
    import services.chapter_agents as ca

    paragraph = "陈玄扣住短刀，沿着树影往前压。他看清泥里的蹄印，又把呼吸放慢，等野猪撞上树干后才侧身出手。"
    content = paragraph * 52 + "他把兽骨塞进布袋，转身听见林子里"

    repaired, changed = ca._repair_truncated_tail_locally(content)

    assert changed is True
    assert repaired.endswith("。")
    assert "转身听见林子里" not in repaired
    assert 2200 <= ca.count_chapter_chars(repaired) <= 2800


def test_repair_truncated_tail_locally_keeps_original_when_repair_too_short():
    import services.chapter_agents as ca

    content = "陈玄扣住短刀，沿着树影往前压。他看清泥里的蹄印。" * 20 + "他把兽骨塞进布袋，转身听见林子里"

    repaired, changed = ca._repair_truncated_tail_locally(content)

    assert changed is False
    assert repaired == content
