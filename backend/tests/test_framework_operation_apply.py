"""测试：framework operation/patch 校验与执行器。"""

from services.framework_utils import apply_framework_operations, validate_framework_operations


def test_validate_framework_operations_rejects_unknown_op():
    errors = validate_framework_operations(
        operations=[{"op": "replace_outline", "target": {}, "changes": {}}],
        patches=[],
    )

    assert errors == ["operations[0].op 不支持: replace_outline"]


def test_validate_framework_operations_rejects_outline_root_patch():
    errors = validate_framework_operations(
        operations=[],
        patches=[{"path": "outline", "value": {"three_acts": []}}],
    )

    assert errors == ["patches[0].path 不支持: outline"]


def test_apply_framework_operations_updates_character_and_chapter():
    framework = {
        "description": "旧描述",
        "tags": {"type": "玄幻", "theme": "成长", "style": "热血", "audience": "男频"},
        "characters": [{"name": "林霁", "role": "主角", "arc": {}, "relationships": []}],
        "outline": {
            "three_acts": [
                {
                    "act": "1",
                    "title": "第一幕",
                    "summary": "起始",
                    "chapters": [
                        {"chapter_number": 1, "title": "开端", "summary": "旧概要"}
                    ],
                }
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {
                "op": "update_character",
                "target": {"name": "林霁"},
                "changes": {"role": "调查者", "motivation": "找出导师隐瞒的真相"},
            },
            {
                "op": "update_chapter",
                "target": {"chapter_number": 1},
                "changes": {"summary": "女主发现第一条异常线索"},
            },
        ],
        patches=[],
    )

    assert result["framework"]["characters"][0]["role"] == "调查者"
    assert result["framework"]["characters"][0]["motivation"] == "找出导师隐瞒的真相"
    assert result["framework"]["outline"]["three_acts"][0]["chapters"][0]["summary"] == "女主发现第一条异常线索"
    assert result["applied_operations"] == [
        "update_character:林霁",
        "update_chapter:1",
    ]
    assert result["errors"] == []


def test_apply_framework_operations_applies_patch_and_delete_chapter():
    framework = {
        "description": "旧描述",
        "tags": {"type": "玄幻", "theme": "成长", "style": "热血", "audience": "男频"},
        "characters": [{"name": "林霁", "role": "主角"}],
        "outline": {
            "three_acts": [
                {
                    "act": "1",
                    "title": "第一幕",
                    "summary": "起始",
                    "chapters": [
                        {"chapter_number": 1, "title": "开端", "summary": "旧概要"},
                        {"chapter_number": 2, "title": "追踪", "summary": "旧概要2"},
                    ],
                }
            ],
            "themes": ["旧主题"],
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[{"op": "delete_chapter", "target": {"chapter_number": 2}, "changes": {}}],
        patches=[{"path": "outline.themes", "value": ["真相", "背叛"]}],
    )

    chapters = result["framework"]["outline"]["three_acts"][0]["chapters"]
    assert [item["chapter_number"] for item in chapters] == [1]
    assert result["framework"]["outline"]["themes"] == ["真相", "背叛"]
    assert result["applied_operations"] == ["delete_chapter:2", "patch:outline.themes"]
    assert result["errors"] == []


def test_apply_add_character():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [{"name": "林霁", "role": "主角"}],
        "outline": {"three_acts": []},
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "add_character", "changes": {"name": "萧然", "role": "反派", "motivation": "复仇"}},
        ],
        patches=[],
    )
    names = [c["name"] for c in result["framework"]["characters"]]
    assert "萧然" in names
    assert "林霁" in names
    assert result["applied_operations"] == ["add_character:萧然"]
    assert result["errors"] == []


def test_apply_remove_character():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [
            {"name": "林霁", "role": "主角"},
            {"name": "萧然", "role": "反派"},
        ],
        "outline": {"three_acts": []},
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "remove_character", "target": {"name": "萧然"}, "changes": {}},
        ],
        patches=[],
    )
    names = [c["name"] for c in result["framework"]["characters"]]
    assert names == ["林霁"]
    assert result["applied_operations"] == ["remove_character:萧然"]
    assert result["errors"] == []


def test_apply_update_story_description():
    framework = {
        "description": "旧描述",
        "tags": {},
        "characters": [],
        "outline": {"three_acts": []},
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "update_story_description", "changes": {"description": "新描述"}},
        ],
        patches=[],
    )
    assert result["framework"]["description"] == "新描述"
    assert result["applied_operations"] == ["update_story_description"]
    assert result["errors"] == []


def test_apply_update_tags():
    framework = {
        "description": "desc",
        "tags": {"type": "玄幻", "theme": "成长"},
        "characters": [],
        "outline": {"three_acts": []},
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "update_tags", "changes": {"theme": "复仇", "style": "暗黑"}},
        ],
        patches=[],
    )
    assert result["framework"]["tags"]["theme"] == "复仇"
    assert result["framework"]["tags"]["style"] == "暗黑"
    assert result["framework"]["tags"]["type"] == "玄幻"
    assert result["applied_operations"] == ["update_tags"]
    assert result["errors"] == []


def test_apply_update_act_summary():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "开端", "summary": "旧概述", "chapters": []},
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "update_act_summary", "target": {"act": "1"}, "changes": {"summary": "新概述"}},
        ],
        patches=[],
    )
    assert result["framework"]["outline"]["three_acts"][0]["summary"] == "新概述"
    assert result["applied_operations"] == ["update_act_summary:1"]
    assert result["errors"] == []


def test_apply_add_chapter():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "开端", "summary": "", "chapters": [
                    {"chapter_number": 1, "title": "第1章", "summary": "旧"}
                ]},
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "add_chapter", "target": {"act": "1"}, "changes": {"chapter_number": 2, "title": "第2章", "summary": "新"}},
        ],
        patches=[],
    )
    chapters = result["framework"]["outline"]["three_acts"][0]["chapters"]
    numbers = [c["chapter_number"] for c in chapters]
    assert 2 in numbers
    assert len(chapters) == 2
    assert result["applied_operations"] == ["add_chapter:2"]
    assert result["errors"] == []


def test_apply_insert_chapter_after():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "开端", "summary": "", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                    {"chapter_number": 3, "title": "第3章"},
                ]},
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "insert_chapter_after", "target": {"chapter_number": 1}, "changes": {"chapter_number": 2, "title": "第2章"}},
        ],
        patches=[],
    )
    chapters = result["framework"]["outline"]["three_acts"][0]["chapters"]
    numbers = [c["chapter_number"] for c in chapters]
    assert numbers == [1, 2, 3]
    assert result["applied_operations"] == ["insert_chapter_after:2"]
    assert result["errors"] == []


def test_apply_move_chapter_to_act():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "第一幕", "summary": "", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                    {"chapter_number": 2, "title": "第2章"},
                ]},
                {"act": "2", "title": "第二幕", "summary": "", "chapters": []},
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "move_chapter_to_act", "target": {"chapter_number": 2, "act": "2"}, "changes": {}},
        ],
        patches=[],
    )
    act1_chapters = result["framework"]["outline"]["three_acts"][0]["chapters"]
    act2_chapters = result["framework"]["outline"]["three_acts"][1]["chapters"]
    assert [c["chapter_number"] for c in act1_chapters] == [1]
    assert [c["chapter_number"] for c in act2_chapters] == [2]
    assert result["applied_operations"] == ["move_chapter_to_act:2"]
    assert result["errors"] == []


def test_apply_update_chapter_with_act_change():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "第一幕", "summary": "", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                ]},
                {"act": "2", "title": "第二幕", "summary": "", "chapters": [
                    {"chapter_number": 2, "title": "第2章"},
                ]},
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {"op": "update_chapter", "target": {"chapter_number": 1}, "changes": {"title": "新标题", "act": "2"}},
        ],
        patches=[],
    )
    act1_chapters = result["framework"]["outline"]["three_acts"][0]["chapters"]
    act2_chapters = result["framework"]["outline"]["three_acts"][1]["chapters"]
    assert [c["chapter_number"] for c in act1_chapters] == []
    assert [c["chapter_number"] for c in act2_chapters] == [1, 2]
    titles = {c["chapter_number"]: c["title"] for c in act2_chapters}
    assert titles[1] == "新标题"
    assert result["applied_operations"] == ["update_chapter:1"]
    assert result["errors"] == []


def test_apply_compress_acts():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "开端", "summary": "旧概述1", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                ]},
                {"act": "2", "title": "发展", "summary": "旧概述2", "chapters": [
                    {"chapter_number": 2, "title": "第2章"},
                ]},
                {"act": "3", "title": "高潮", "summary": "旧概述3", "chapters": [
                    {"chapter_number": 3, "title": "第3章"},
                ]},
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[],
        patches=[{
            "path": "outline.three_acts",
            "value": [
                {"act": "1", "title": "开端与发展", "summary": "合并概述", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                    {"chapter_number": 2, "title": "第2章"},
                ]},
                {"act": "2", "title": "高潮与结局", "summary": "合并概述2", "chapters": [
                    {"chapter_number": 3, "title": "第3章"},
                ]},
            ],
        }],
    )
    acts = result["framework"]["outline"]["three_acts"]
    assert len(acts) == 2
    assert acts[0]["title"] == "开端与发展"
    assert [c["chapter_number"] for c in acts[0]["chapters"]] == [1, 2]
    assert [c["chapter_number"] for c in acts[1]["chapters"]] == [3]
    assert "patch:outline.three_acts" in result["applied_operations"]
    assert result["errors"] == []
