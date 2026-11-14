"""画布级风格：补入无自带风格的生成节点、参与复用指纹、随资产分析传给文本模型。"""

import asyncio

import pytest

from services import canvas_asset_analysis as analysis
from services import deepseek as deepseek_service
from services import video_canvas_director as director
from services import video_canvas_runtime as runtime
from services.canvas_run_reuse import definition_hash
from services.canvas_style import apply_canvas_style, canvas_style, has_own_style, style_prompt_hint

PRESET = {"style_preset_id": 3, "style_snapshot": {"name": "国风水墨", "prompt_template": "水墨晕染，留白，淡雅设色", "image_url": "https://cdn.example/ink.png"}}


def graph(style=None, node_config=None):
    metadata = {"canvas_style": style} if style else {}
    return {
        "metadata": metadata,
        "nodes": [{"id": "shot", "type": "image", "data": {"config": dict(node_config or {"prompt": "少女撑伞"})}}],
        "edges": [],
    }


def test_valid_styles_are_read_and_invalid_ones_ignored():
    assert canvas_style(graph(PRESET))["style_snapshot"]["name"] == "国风水墨"
    assert canvas_style(graph({"style_reference_asset_id": 9, "style_reference_url": "/static/x.png"}))["style_reference_asset_id"] == 9
    assert canvas_style(graph()) is None
    assert canvas_style(graph({"style_snapshot": {}})) is None
    assert canvas_style(graph({"style_reference_asset_id": True})) is None


def test_generation_nodes_without_own_style_receive_the_canvas_style():
    result = apply_canvas_style("image", {"prompt": "p"}, canvas_style(graph(PRESET)))
    assert result["style_snapshot"]["name"] == "国风水墨" and result["style_preset_id"] == 3


def test_node_level_style_wins_and_non_generation_nodes_are_untouched():
    style = canvas_style(graph(PRESET))
    own = {"prompt": "p", "style_snapshot": {"name": "赛博朋克", "prompt_template": "霓虹"}}
    assert apply_canvas_style("image", own, style)["style_snapshot"]["name"] == "赛博朋克"
    own_reference = {"style_reference_asset_id": 5}
    assert has_own_style(own_reference) and "style_snapshot" not in apply_canvas_style("video", own_reference, style)
    assert "style_snapshot" not in apply_canvas_style("screenplay", {"content": "x"}, style)


def test_changing_canvas_style_changes_the_reuse_fingerprint():
    without = definition_hash(graph(), "shot")
    with_style = definition_hash(graph(PRESET), "shot")
    other = definition_hash(graph({**PRESET, "style_snapshot": {"name": "赛博朋克", "prompt_template": "霓虹"}}), "shot")
    assert len({without, with_style, other}) == 3
    assert definition_hash(graph(PRESET), "shot") == with_style


def test_node_level_style_makes_canvas_style_irrelevant_to_the_fingerprint():
    own = {"prompt": "p", "style_snapshot": {"name": "赛博朋克", "prompt_template": "霓虹"}}
    assert definition_hash(graph(PRESET, own), "shot") == definition_hash(graph(None, own), "shot")


def test_injected_style_reaches_the_prompt_and_reference_image():
    config = apply_canvas_style("image", {"prompt": "p"}, canvas_style(graph(PRESET)))
    assert "风格要求：水墨晕染，留白，淡雅设色" in runtime._apply_style_prompt("少女撑伞", config, [])


def test_prompt_hint_describes_the_style():
    assert style_prompt_hint(canvas_style(graph(PRESET))) == "国风水墨：水墨晕染，留白，淡雅设色"
    assert "参考图" in style_prompt_hint(canvas_style(graph({"style_reference_asset_id": 9})))
    assert style_prompt_hint(None) == ""


def test_asset_analysis_never_puts_style_text_into_prompts(monkeypatch):
    seen = {}

    async def fake_json(**kwargs):
        seen["user"] = kwargs["user"]
        return {"style": {"art_style": "模型自选画风"}, "characters": [{"name": "顾沉", "profile": "实习生"}]}

    async def fake_character(shot_data, character_profiles="", api_key=None):
        return [{"name": "顾沉", "prompt": "顾沉三视图\n统一视觉风格：模型自带的风格行\nVisual style: cinematic"}]

    monkeypatch.setattr(director, "_call_deepseek_json", fake_json)
    monkeypatch.setattr(analysis, "generate_character_prompts", fake_character)
    scenes = [{"scene_id": "1", "location": "宴会厅", "characters": ["顾沉"], "beats": [{"source_text": "顾沉走进宴会厅"}]}]
    result = asyncio.run(analysis.analyze_scene_assets(scenes=scenes, screenplay_text="顾沉走进宴会厅", style_hint="国风水墨：水墨晕染"))
    # 风格文字不交给文本模型，也不写进资产提示词：画风只由风格参考图控制
    assert "国风水墨" not in seen["user"] and "用户已选定画风" not in seen["user"]
    prompt = result["assets"][0]["prompt"]
    assert prompt == "顾沉三视图" and "国风水墨" not in prompt and "模型自选画风" not in prompt


def test_strip_style_text_and_runtime_ignores_stale_style_lines():
    from services.canvas_style import strip_style_text
    from services import video_canvas_runtime as rt

    stale = "一个少女\n统一视觉风格：写实电影感：Realistic cinematic style, film grain\n全身站姿 | 【风格】水墨"
    assert strip_style_text(stale) == "一个少女\n全身站姿"
    anchor = [{"url": "https://oss.example/s.png", "style_anchor": True}]
    # 有风格参考图：只保留“以画风参考图为准”，不再附加预设的风格文字
    text = rt._apply_style_prompt("一个少女", {"style_snapshot": {"prompt_template": "Realistic cinematic style"}}, anchor)
    assert "画风参考图为准" in text and "Realistic cinematic" not in text
    # 没有风格图的预设仍用文字兜底
    assert "Realistic cinematic style" in rt._apply_style_prompt("一个少女", {"style_snapshot": {"prompt_template": "Realistic cinematic style"}}, [])


def test_global_switch_off_disables_the_canvas_style_everywhere():
    off = {**PRESET, "enabled": False}
    assert canvas_style(graph(off)) is None
    # 关闭后节点不再补入风格，复用指纹与"没有画布风格"时一致
    assert apply_canvas_style("image", {"prompt": "p"}, canvas_style(graph(off))) == {"prompt": "p"}
    assert definition_hash(graph(off), "shot") == definition_hash(graph(), "shot")
    assert canvas_style(graph({**PRESET, "enabled": True})) is not None


def test_assistant_is_told_the_style_and_switch_state():
    from services.canvas_style import describe_canvas_style

    assert "还没有选择" in describe_canvas_style(graph())
    assert "全局画风已开启" in describe_canvas_style(graph(PRESET)) and "国风水墨" in describe_canvas_style(graph(PRESET))
    assert "开关已关闭" in describe_canvas_style(graph({**PRESET, "enabled": False}))
