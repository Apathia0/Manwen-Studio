from importlib import import_module

from services.author_style import select_author_style_samples
from prompts.deconstruction import AUTHOR_ROUTINE_MERGE_USER, AUTHOR_STYLE_REPORT_USER, AUTHOR_STYLE_SAMPLE_USER
from services.author_style import ANONYMIZED_SOURCE_AUTHOR, ANONYMIZED_SOURCE_TITLE, build_anonymized_author_style_profile


def test_select_author_style_samples_uses_all_when_short():
    chapters = list(range(1, 8))

    assert select_author_style_samples(chapters) == chapters


def test_select_author_style_samples_caps_long_books():
    chapters = list(range(1, 201))

    selected = select_author_style_samples(chapters)

    assert selected == sorted(set(selected))
    assert selected[:3] == [1, 2, 3]
    assert 199 in selected
    assert 200 in selected
    assert 16 <= len(selected) <= 20


def test_select_author_style_samples_medium_books_include_tail():
    chapters = list(range(1, 41))

    selected = select_author_style_samples(chapters)

    assert selected == sorted(set(selected))
    assert selected[:3] == [1, 2, 3]
    assert 40 in selected
    assert 12 <= len(selected) <= 15


def test_author_routine_merge_prompt_format_preserves_json_schema():
    prompt = AUTHOR_ROUTINE_MERGE_USER.format(
        title="测试作品",
        author="测试作者",
        sampled_chapters="[1, 2, 3]",
        sample_results='[{"chapter_number": 1}]',
    )

    assert '"schema_version": 1' in prompt
    assert '"style_profile"' in prompt
    assert '仅返回 JSON。' in prompt


def test_author_style_prompts_hide_source_title_and_author():
    real_title = "玄鉴仙族"
    real_author = "季越人"

    sample_prompt = AUTHOR_STYLE_SAMPLE_USER.format(
        title=ANONYMIZED_SOURCE_TITLE,
        author=ANONYMIZED_SOURCE_AUTHOR,
        chapter_number=1,
        chapter_title="第一章",
        word_count=3000,
        chapter_text="样本文本",
    )
    report_prompt = AUTHOR_STYLE_REPORT_USER.format(
        title=ANONYMIZED_SOURCE_TITLE,
        author=ANONYMIZED_SOURCE_AUTHOR,
        profile_json='{"source_policy":"anonymized"}',
    )

    combined = sample_prompt + report_prompt
    assert real_title not in combined
    assert real_author not in combined
    assert ANONYMIZED_SOURCE_TITLE in combined
    assert ANONYMIZED_SOURCE_AUTHOR in combined


def test_author_style_profile_marks_anonymized_source():
    profile = build_anonymized_author_style_profile({
        "routine_cards": [],
        "title": "玄鉴仙族",
        "author": "季越人",
        "source_title": "玄鉴仙族",
        "source_author": "季越人",
    }, [1, 2, 3])

    assert profile["source_policy"] == "anonymized"
    assert profile["source_label"] == "匿名样本"
    assert profile["sampled_chapters"] == [1, 2, 3]
    assert "title" not in profile
    assert "author" not in profile
    assert "source_title" not in profile
    assert "source_author" not in profile


def test_author_style_reference_is_available_to_story_context():
    deepseek = import_module("services.deepseek")
    story_state = import_module("services.story_state")
    story_bible = {
        "reference_author_profile": {
            "source_policy": "anonymized",
            "routine_cards": [{"name": "开局压迫感", "usage": "第一章迅速制造主角困境"}],
        },
        "reference_author_report": "作者画像报告：短句推进，场景压力强，情绪转折清晰。",
    }

    compact = story_state.build_story_bible_compact(story_bible)
    snapshot = deepseek._build_story_snapshot({"story_bible": story_bible})

    assert compact["reference_author_profile"]["source_policy"] == "anonymized"
    assert compact["reference_author_report"] == "作者画像报告：短句推进，场景压力强，情绪转折清晰。"
    assert "作者画像参考报告" in snapshot
    assert "短句推进" in snapshot
    assert "作者风格画像" in snapshot


def test_author_style_reference_injected_into_tiered_snapshot():
    deepseek = import_module("services.deepseek")
    story_bible = {
        "creative_brief": {"project_positioning": "都市异能"},
        "reference_author_profile": {
            "source_policy": "anonymized",
            "routine_cards": [{"name": "节奏加速", "usage": "冲突升级快"}],
        },
        "reference_author_report": "作者画像报告：高频对话推进，场景切换密集。",
    }

    snapshot_auto = deepseek._build_story_snapshot_tiered({"story_bible": story_bible}, "auto")

    assert "作者风格画像" in snapshot_auto
    assert "作者画像参考报告" in snapshot_auto
    assert "高频对话推进" in snapshot_auto
