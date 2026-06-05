"""测试：framework adjust 结构化编辑计划流程。"""

from services.deepseek import _extract_framework_adjustment_plan


from services.framework_utils import apply_framework_operations, validate_applied_framework_consistency


def test_validate_applied_framework_consistency_accepts_existing_missing_tags():
    framework = {
        "description": "desc",
        "tags": {},
        "characters": [{"name": "A", "role": "主角"}],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "幕", "summary": "", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                ]},
            ]
        },
    }
    assert validate_applied_framework_consistency(framework) == []


def test_validate_applied_framework_consistency_rejects_duplicate_chapter_numbers():
    framework = {
        "description": "desc",
        "tags": {"type": "x", "theme": "y", "style": "z", "audience": "w"},
        "characters": [{"name": "A", "role": "主角"}],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "幕", "summary": "", "chapters": [
                    {"chapter_number": 1, "title": "第1章"},
                    {"chapter_number": 1, "title": "第1章重复"},
                ]},
            ]
        },
    }
    errors = validate_applied_framework_consistency(framework)
    assert "chapter_number 存在重复" in errors


def test_extract_framework_adjustment_plan_returns_operations_and_warnings():
    raw = {
        "reply": "已强化主角调查动机，并删除第 8 章。",
        "operations": [
            {"op": "update_character", "target": {"name": "林霁"}, "changes": {"motivation": "追查导师"}},
            {"op": "delete_chapter", "target": {"chapter_number": 8}, "changes": {}},
        ],
        "patches": [{"path": "outline.themes", "value": ["真相", "代价"]}],
        "warnings": ["未处理配角支线"]
    }

    result = _extract_framework_adjustment_plan(raw)

    assert result["reply"] == "已强化主角调查动机，并删除第 8 章。"
    assert len(result["operations"]) == 2
    assert result["patches"] == [{"path": "outline.themes", "value": ["真相", "代价"]}]
    assert result["warnings"] == ["未处理配角支线"]
