"""_extract_json_object 截断 JSON 修复测试。

背景：DeepSeek 长输出（如 generate_framework，10+ 章节规划）常被上游
max_tokens 实际上限截断，_extract_json_object 兜底链此前不接入
_repair_truncated_json，导致「响应不是有效的 JSON」直接 502。
"""
import json
import pytest

from services import deepseek


class TestExtractJsonObjectTruncationRepair:
    """截断 JSON 应走 _repair_truncated_json 抢救已生成的前半结构。"""

    def test_repairs_truncated_string_value(self):
        """字符串值中途截断：补引号与括号后应返回 dict。"""
        raw = (
            '{"tags": ["都市", "悬疑"], '
            '"characters": [{"name": "林默", "summary": "冷静的程序员'
        )
        result = deepseek._extract_json_object(raw)
        assert isinstance(result, dict)
        assert result["tags"] == ["都市", "悬疑"]
        assert result["characters"][0]["name"] == "林默"

    def test_repairs_truncated_key_name_with_null_value(self):
        """键名截断：孤儿键应补 :null（陷阱 #9 场景）。"""
        raw = (
            '{"tags": ["都市"], '
            '"chapters": [{"chapter_number": 1, "title": "第一章", "key_'
        )
        result = deepseek._extract_json_object(raw)
        assert result["tags"] == ["都市"]
        assert result["chapters"][0]["chapter_number"] == 1

    def test_repairs_nested_truncation_in_lifo_order(self):
        """嵌套结构截断：闭合顺序必须 LIFO（}] 而非 }}]，陷阱 #9 场景）。"""
        raw = '{"outline": {"acts": [{"name": "第一幕", "summary": "主角登场'
        result = deepseek._extract_json_object(raw)
        assert result["outline"]["acts"][0]["name"] == "第一幕"

    def test_repairs_truncation_before_any_closing_brace(self):
        """全文无任何闭括号的极端截断：仍应抢救出 dict。"""
        raw = '{"tags": ["男频", "悬'
        result = deepseek._extract_json_object(raw)
        assert result["tags"] == ["男频", "悬"]

    def test_repairs_regex_candidate_with_unterminated_string(self):
        """截断点前存在内层闭括号：正则提取的 candidate 字符串未终止也应被修复。"""
        raw = (
            '{"tags": ["都市"], "chapters": ['
            '{"chapter_number": 1, "title": "第一章"}, '
            '{"chapter_number": 2, "summary": "第'
        )
        result = deepseek._extract_json_object(raw)
        assert result["chapters"][0]["chapter_number"] == 1
        assert result["chapters"][1]["chapter_number"] == 2

    def test_valid_json_unchanged(self):
        """合法 JSON 不受影响（回归）。"""
        raw = '{"tags": ["都市"], "chapters": []}'
        assert deepseek._extract_json_object(raw) == json.loads(raw)

    def test_valid_json_array_still_raises(self):
        """合法 JSON 数组仍应抛「不是对象」，不得被截断修复吞掉（回归）。"""
        with pytest.raises(ValueError, match="不是对象"):
            deepseek._extract_json_object('[{"shot_index": 1}]')

    def test_plain_text_still_raises(self):
        """纯文本非 JSON 仍应抛错（回归）。"""
        with pytest.raises(ValueError):
            deepseek._extract_json_object("这不是 JSON，只是一段普通文本。")
