import json

import pytest

from services import chapter_quality
from services import chapter_agents
from services.chapter_quality import (
    count_content_chars,
    finalize_generated_chapter_content,
    run_deterministic_gate,
)
from services.deepseek import build_agent_chapter_system_prompt


def make_content(chars: int, prefix: str = "林墨推开门，血腥味从院子里扑出来。") -> str:
    filler = "他抬手按住门框，听见屋内有人低声叫他的名字。"
    text = prefix
    while count_content_chars(text) < chars:
        text += filler
    return text[:chars]


def test_count_content_chars_ignores_whitespace():
    assert count_content_chars("林墨\n 推开 门\r") == 5


def test_gate_allows_overlong_non_empty_content():
    report = run_deterministic_gate(make_content(3600), {"chapter_number": 4})
    assert report["ok"] is True
    assert report["char_count"] == 3600
    assert report["target"] == {"min": 2200, "ideal": 2500, "max": 3000}
    assert all(not item["code"].startswith("length.") for item in report["hard_failures"])


def test_gate_allows_short_non_empty_content():
    report = run_deterministic_gate(make_content(1200), {"chapter_number": 4})
    assert report["ok"] is True
    assert report["char_count"] == 1200
    assert report["target"] == {"min": 2200, "ideal": 2500, "max": 3000}
    assert all(not item["code"].startswith("length.") for item in report["hard_failures"])


def test_gate_rejects_ai_flavor_patterns():
    content = make_content(2200) + "\n他眼中闪过一丝复杂，仿佛命运的齿轮开始转动。"
    report = run_deterministic_gate(content, {"chapter_number": 4})
    codes = {item["code"] for item in report["warnings"]}
    assert report["ok"] is True
    assert "ai_flavor.forbidden_phrase" in codes
    assert "ai_flavor.simile" in codes


def test_gate_warns_first_chapter_weather_opening():
    content = make_content(2200, prefix="清晨的阳光落在青石板上，雾气还没有散尽。林墨推开门。")
    report = run_deterministic_gate(content, {"chapter_number": 1})
    assert report["ok"] is True
    assert any(item["code"] == "opening.weak_time_or_scenery_opening" for item in report["warnings"])


def test_gate_warns_later_chapter_time_opening():
    content = make_content(2300, prefix="清晨六点半，陈玄推开出租屋的门。巷子里没人，早餐摊冒着热气。")
    report = run_deterministic_gate(content, {"chapter_number": 3})
    assert report["ok"] is True
    assert any(item["code"] == "opening.weak_time_or_scenery_opening" for item in report["warnings"])


def test_gate_rejects_future_chapter_payoff_even_when_length_passes():
    content = make_content(2300, prefix="林墨推开门，血腥味从院子里扑出来。他摸到袖中的地下武道擂台传单。")
    chapter_scope = {
        "current_chapter_number": 1,
        "current_chapter_card": {
            "chapter_number": 1,
            "title": "绝境开局",
            "summary": "主角确认母亲重病、债主上门和自己赤贫处境。",
        },
        "previous_chapters_for_continuity": [],
        "future_chapters_for_boundary_only": [
            {
                "chapter_number": 3,
                "title": "登台擂台，初战破局",
                "summary": "主角踏入地下武道擂台，借力打力取胜并获得奖金。",
            }
        ],
    }

    report = run_deterministic_gate(content, {"chapter_number": 1}, chapter_scope=chapter_scope)

    assert report["ok"] is False
    assert any(item["code"] == "boundary.future_event" for item in report["hard_failures"])


def test_gate_rejects_second_chapter_old_boundary_leaks():
    content = make_content(
        2300,
        prefix=(
            "陈玄把药草压进陶碗，先试汤色，再用银针探热。"
            "他清楚擂台这条路在肉身进入淬体境时就会封死，低级异兽也不是现在该碰的东西。"
        ),
    )
    chapter_scope = {
        "current_chapter_number": 2,
        "current_chapter_card": {
            "chapter_number": 2,
            "title": "坊市捡漏，古法炼身",
            "summary": "主角在坊市捡漏旧药材，以古法调配汤药完成第一次炼身。",
        },
        "previous_chapters_for_continuity": [
            {"chapter_number": 1, "title": "仙尊落凡，绝境凡尘", "summary": "主角确认病母、债务和凡人处境。"}
        ],
        "future_chapters_for_boundary_only": [
            {
                "chapter_number": 3,
                "title": "登台擂台，初战破局",
                "summary": "主角踏入地下武道擂台，借力打力取胜并获得奖金。",
            },
            {
                "chapter_number": 6,
                "title": "荒域遇兽，生死磨砺",
                "summary": "主角在荒域遭遇低级异兽，借神魂预判完成生死搏杀。",
            },
        ],
    }

    report = run_deterministic_gate(content, {"chapter_number": 2}, chapter_scope=chapter_scope)

    assert report["ok"] is False
    messages = "\n".join(item["message"] for item in report["hard_failures"])
    assert "擂台" in messages
    assert "低级异兽" in messages


def test_gate_does_not_flag_generic_future_stopwords():
    content = make_content(
        2300,
        prefix="陈玄翻过城防告示，只确认城外活动范围和官方开放的路段，没有再往荒地深处走。",
    )
    chapter_scope = {
        "current_chapter_number": 2,
        "current_chapter_card": {
            "chapter_number": 2,
            "title": "坊市捡漏，古法炼身",
            "summary": "主角在坊市处理药材和汤药，不进入荒域。",
        },
        "previous_chapters_for_continuity": [],
        "future_chapters_for_boundary_only": [
            {
                "chapter_number": 4,
                "title": "荒域初探，秘境之门",
                "summary": "官方开放活动范围后，主角确认城外荒域边界。",
            }
        ],
    }

    report = run_deterministic_gate(content, {"chapter_number": 2}, chapter_scope=chapter_scope)

    assert not any(item["code"] == "boundary.future_event" for item in report["hard_failures"]), report


def test_creation_pack_sanitizes_future_boundary_terms():
    pack = {
        "plot_beats": [
            "陈玄登上擂台，借力打力赢下对手，领到奖金。",
            "陈玄翻出秘境地图，确认荒域路线。",
        ],
        "ending_hook": "他摸到口袋里的秘境地图折角，意识到荒域入口就在眼前。",
        "must_keep": ["本章必须完成擂台胜利。", "章尾点出灵草采集目标。"],
        "style_brief": "节奏利落，最后用异兽气息和秘境入口做钩子。",
        "do_not_write": [],
    }
    chapter_scope = {
        "current_chapter_number": 3,
        "current_chapter_card": {
            "chapter_number": 3,
            "title": "登台擂台，初战破局",
            "summary": "地下武道擂台，以弱搏强，借力打力取胜，获奖金缓解经济压力。",
        },
        "previous_chapters_for_continuity": [],
        "future_chapters_for_boundary_only": [
            {
                "chapter_number": 4,
                "title": "荒域初探，秘境之门",
                "summary": "主角确认荒域入口，获得秘境地图并准备探索路线。",
            },
            {
                "chapter_number": 5,
                "title": "潜行采集，灵草初获",
                "summary": "主角进入荒域采集灵草。",
            },
            {
                "chapter_number": 6,
                "title": "异兽初猎，技术制胜",
                "summary": "主角猎杀低级异兽。",
            },
        ],
    }

    sanitized = chapter_agents._sanitize_creation_pack_boundary(pack, chapter_scope)

    assert "奖金" in sanitized["plot_beats"][0]
    assert len(sanitized["plot_beats"]) == 1
    writable_text = "\n".join(
        [
            "\n".join(sanitized.get("plot_beats", [])),
            sanitized.get("ending_hook", ""),
            "\n".join(sanitized.get("must_keep", [])),
            sanitized.get("style_brief", ""),
        ]
    )
    for term in ("荒域", "秘境", "灵草", "异兽"):
        assert term not in writable_text
    assert sanitized["boundary_sanitization"]["removed_terms"]
    assert "荒域" in sanitized["future_boundary_terms"]
    assert any("禁止写进正文" in item for item in sanitized["do_not_write"])


def test_editor_feedback_sanitizes_future_boundary_suggestions():
    creation_pack = {
        "chapter_boundary": {
            "current_chapter_number": 3,
            "current_chapter_card": {
                "chapter_number": 3,
                "title": "登台擂台，初战破局",
                "summary": "主角踏入地下武道擂台，以弱搏强获胜并得到奖金。",
            },
            "future_chapters_for_boundary_only": [
                {
                    "chapter_number": 4,
                    "title": "荒域初探，秘境之门",
                    "summary": "主角获得秘境地图，确认荒域路线。",
                }
            ],
        }
    }
    chapter_agents._sanitize_creation_pack_boundary(creation_pack, creation_pack["chapter_boundary"])

    feedback = chapter_agents._sanitize_editor_feedback(
        [
            "补足报名等待区的对话和观众反应。",
            "章尾让主角回家翻看秘境地图，规划荒域路线。",
            "删除所有预支秘境的内容。",
        ],
        creation_pack,
    )

    joined = "\n".join(feedback)
    assert "报名等待区" in joined
    assert "删除所有预支秘境" in joined
    assert "翻看秘境地图" not in joined
    assert "忽略任何要求新增后续章节地点" in joined


@pytest.mark.asyncio
async def test_creation_pack_replaces_empty_agent_boundary(monkeypatch):
    async def fake_chat_completion(**kwargs):
        return (
            json.dumps(
                {
                    "chapter_task": {"chapter_number": 3},
                    "plot_beats": ["完成擂台战斗并领取奖金。"],
                    "ending_hook": "停在当前事件余波。",
                    "must_keep": [],
                    "do_not_write": [],
                    "chapter_boundary": {},
                },
                ensure_ascii=False,
            ),
            "stop",
        )

    monkeypatch.setattr(chapter_agents, "_chat_completion", fake_chat_completion)

    pack = await chapter_agents.build_chapter_creation_pack(
        story_context={
            "current_chapter": {"chapter_number": 3},
            "outline": {
                "three_acts": [
                    {
                        "act": "1",
                        "chapters": [
                            {
                                "chapter_number": 3,
                                "title": "登台擂台，初战破局",
                                "summary": "主角踏入地下武道擂台，以弱搏强获胜并得到奖金。",
                            },
                            {
                                "chapter_number": 4,
                                "title": "荒域初探，秘境之门",
                                "summary": "主角获得秘境地图，确认荒域路线。",
                            },
                        ],
                    }
                ]
            },
        },
        chapter_info={"chapter_number": 3},
        api_key="sk-test",
    )

    assert pack["chapter_boundary"]["future_chapters_for_boundary_only"]
    assert "荒域" in pack["future_boundary_terms"]
    assert any("禁止写进正文" in item for item in pack["do_not_write"])


def test_gate_accepts_dense_qidian_like_content():
    content = make_content(2300)
    report = run_deterministic_gate(content, {"chapter_number": 4})
    assert report["ok"] is True
    assert report["char_count"] >= 2200


@pytest.mark.asyncio
async def test_editor_review_retries_when_json_parse_fails(monkeypatch):
    calls: list[dict] = []

    async def fake_chat_completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return "这次我先用自然语言点评，导致无法解析。", "stop"
        return (
            json.dumps(
                {
                    "approved": True,
                    "overall_score": 93,
                    "scores": {"overall": 93, "brief_execution": 94, "boundary_control": 92},
                    "findings": ["字数合格，剧情闭环完整。"],
                    "revision_notes": ["无需返修。"],
                    "length_action": "字数合格，无需调整。",
                    "blocking_issues": [],
                    "keep": ["保留当前章猎杀、采集、撤离和代价。"],
                    "fill": [],
                    "cut": [],
                    "forbid": ["禁止展开后续交易。"],
                    "rewrite_targets": [],
                    "revision_plan": ["无需返修"],
                    "rewrite_brief": ["无需返修。"],
                },
                ensure_ascii=False,
            ),
            "stop",
        )

    monkeypatch.setattr(chapter_agents, "_chat_completion", fake_chat_completion)

    review = await chapter_agents.review_chapter_with_editor_agent(
        creation_pack={
            "chapter_task": {"chapter_number": 6, "title": "异兽初猎，技术制胜"},
            "chapter_boundary": {},
            "hard_requirements": ["猎杀獠牙野猪", "采集精血、獠牙和兽骨"],
            "closure_requirements": ["清理现场并撤离", "写清身体代价和当前压力"],
            "missing_if_absent": ["缺少采集和撤离必须打回"],
        },
        content=make_content(2300, prefix="陈玄伏在乱石后，盯着獠牙野猪的肩胛起伏。"),
        api_key="sk-real",
    )

    assert len(calls) == 2
    assert "上一次编辑审阅输出不是合法 JSON" in calls[1]["messages"][1]["content"]
    assert review["approved"] is True
    assert review["overall_score"] == 93
    assert review["raw"]["length_action"] == "字数合格，无需调整。"


@pytest.mark.asyncio
async def test_finalize_repairs_then_accepts(monkeypatch):
    bad = make_content(3100)
    good = make_content(2300)

    async def fake_pipeline(**kwargs):
        return {
            "ok": True,
            "content": good,
            "attempts": 1,
            "review": {"approved": True, "overall_score": 93},
            "creation_pack": {"writer_brief": "测试创作包"},
            "finish_reason": "stop",
        }

    monkeypatch.setattr(chapter_agents, "run_chapter_creation_pipeline", fake_pipeline)

    result = await finalize_generated_chapter_content(
        content=bad,
        story_context={},
        chapter_info={
            "chapter_number": 4,
            "goal": "推进冲突",
            "conflict": "追兵入院",
            "hook": "门外来人",
            "payoff": "主角反制",
            "highlight": "身份暴露",
        },
        api_key="test",
        system_prompt=None,
        source="test",
    )

    assert result["ok"] is True
    assert result["attempts"] == 1
    assert result["content"] == good


@pytest.mark.asyncio
async def test_finalize_returns_failure_after_repair_limit(monkeypatch):
    bad = make_content(3600)

    async def fake_pipeline(**kwargs):
        return {
            "ok": False,
            "content": bad,
            "attempts": 2,
            "review": {"approved": False, "overall_score": 65},
            "creation_pack": {"writer_brief": "测试创作包"},
            "finish_reason": "stop",
        }

    monkeypatch.setattr(chapter_agents, "run_chapter_creation_pipeline", fake_pipeline)

    result = await finalize_generated_chapter_content(
        content=bad,
        story_context={},
        chapter_info={"chapter_number": 4},
        api_key="test",
        system_prompt=None,
        source="test",
        max_attempts=2,
    )

    assert result["ok"] is False
    assert result["attempts"] == 2
    assert result["report"]["deterministic"]["ok"] is True
    assert result["report"]["deterministic"]["hard_failures"] == []


def test_chapter_system_prompt_contains_beat_and_gate_rules():
    prompt = build_agent_chapter_system_prompt()
    assert "叙事 beat" in prompt or "叙事节拍" in prompt
    assert "合格才保存" in prompt or "质量门禁" in prompt
    assert "禁止破折号" in prompt
