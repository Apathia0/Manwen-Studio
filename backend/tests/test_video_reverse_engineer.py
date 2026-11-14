"""测试视频逆向分析编排服务 V3（直接视频输入方案）。"""

import asyncio

import pytest
from unittest.mock import MagicMock

from services.errors import UpstreamServiceError


def test_analyze_video_direct_creates_workflow(mocker):
    """测试 V3 analyze_video 整体流程（mock 外部依赖）。"""
    from services.video_reverse_engineer import analyze_video

    # Mock 视频时长
    mock_subprocess = mocker.patch("services.video_reverse_engineer.subprocess.run")
    mock_result = MagicMock()
    mock_result.stdout = "5.8\n"
    mock_subprocess.return_value = mock_result

    # Mock VLM 直接视频分析响应（观察层）
    observation_response = """{
        "overall": {
            "total_duration_seconds": 5.8,
            "num_shots": 2,
            "video_type": "Vlog",
            "general_atmosphere": "温馨日常记录"
        },
        "shots": [
            {
                "shot_index": 1, "start_second": 0.0, "end_second": 2.3, "duration_seconds": 2.3,
                "scene": {"location_type": "室内", "setting": "客厅", "background": "沙发茶几",
                    "depth_layers": {"foreground": "咖啡杯", "midground": "人物", "background": "窗帘"}},
                "characters": [{"character_id": "character_1", "gender": "女", "age_group": "青年",
                    "facial_expression": "微笑", "body_posture": "坐于沙发", "clothing": "红色连衣裙",
                    "hairstyle": "长发", "held_items": [], "action_in_shot": "翻书"}],
                "camera": {"shot_type": "中景", "angle": "平视", "composition": "三分法",
                    "camera_movement": "固定", "camera_movement_description": "", "focus": "浅景深"},
                "lighting": {"primary_light_source": "窗户自然光", "lighting_quality": "柔光",
                    "color_palette": "暖红金黄", "contrast": "中", "saturation": "中", "shadow_detail": "柔阴影"},
                "visual_beats": [],
                "dialogue_heard": "(无)",
                "props": [], "environment_effects": [], "time_of_day": "黄昏"
            },
            {
                "shot_index": 2, "start_second": 2.3, "end_second": 5.8, "duration_seconds": 3.5,
                "scene": {"location_type": "室外", "setting": "街道", "background": "行人商铺",
                    "depth_layers": {"foreground": "", "midground": "人物", "background": "街景"}},
                "characters": [{"character_id": "character_2", "gender": "女", "age_group": "青年",
                    "facial_expression": "大笑", "body_posture": "行走", "clothing": "白色T恤",
                    "hairstyle": "短发", "held_items": ["手机"], "action_in_shot": "边走边看手机"}],
                "camera": {"shot_type": "全景", "angle": "仰拍", "composition": "引导线",
                    "camera_movement": "跟拍", "camera_movement_description": "侧面跟拍角色行走", "focus": "深景深"},
                "lighting": {"primary_light_source": "太阳顶光", "lighting_quality": "硬光",
                    "color_palette": "蓝白灰", "contrast": "高", "saturation": "低", "shadow_detail": "硬阴影"},
                "visual_beats": [
                    {"time_seconds": 4.0, "beat_type": "camera_move_change",
                     "description": "跟拍速度减慢转为固定镜头"}
                ],
                "dialogue_heard": "角色说：'今天天气真好'",
                "props": ["手机"], "environment_effects": [], "time_of_day": "白天"
            }
        ]
    }"""

    mocker.patch(
        "services.visual_api.analyze_video_direct",
        return_value=observation_response,
    )

    # Mock 文本 LLM 调用（4层：角色注册 → 风格分析 → 导演分析 → 提示词反推）
    mock_text_calls = [
        # 角色注册
        '''{"characters": [{"character_id": "character_1", "display_name": "少女",
            "visual_profile": {"gender": "女", "age_group": "青年", "clothing_throughout": {"consistent": true}},
            "appearances": {"total_shots": 1, "shot_indices": [1]},
            "cross_shot_consistency": {"all_characters_tracked": true}}],
          "cross_shot_consistency": {"all_characters_tracked": true}}''',
        # 风格分析
        '''{"style_breakdown": {"cinematography": {"dominant_shot_types": ["中景", "全景"],
            "camera_movement_style": "固定和跟拍", "composition_pattern": "三分法和引导线"},
            "color_grading": {"primary_palette": "暖红+蓝白", "contrast_style": "中等"},
            "lighting_system": {"primary_method": "自然光为主"},
            "production_design": {}, "visual_rhythm": {"editing_pace": "中等"}},
          "summary": {"overall_style_description": "写实风格的日常Vlog"}}''',
        # 导演分析
        '''{"video_type": "Vlog", "narrative_structure": {"pattern": "时间顺序", "overall_rhythm": "轻快", "shots_analysis": []},
            "emotion_curve": {"overall_tone": "温馨", "shots": []},
            "director_intent": {"summary": "日常记录", "shot_analysis": []},
            "visual_style": {"cinematography": "纪实风格", "color_scheme": "自然", "visual_motifs": [], "comparable_styles": []}}''',
        # 提示词反推
        '''{"global_prompt": {"style": "纪实日常风格", "cinematic_reference": "", "mood": "温馨"},
            "character_prompts": [], "shot_prompts": []}''',
    ]
    mocker.patch(
        "services.video_reverse_engineer._call_text_llm",
        side_effect=mock_text_calls,
    )

    # Mock JSON 解析
    mocker.patch(
        "services.deepseek._loads_json_lenient",
        side_effect=[
            # 观察层解析
            {"overall": {"total_duration_seconds": 5.8, "num_shots": 2},
             "shots": [
                {"shot_index": 1, "start_second": 0.0, "end_second": 2.3, "scene": {}, "camera": {}, "lighting": {}, "characters": [], "visual_beats": [], "props": [], "environment_effects": [], "time_of_day": ""},
                {"shot_index": 2, "start_second": 2.3, "end_second": 5.8, "scene": {}, "camera": {}, "lighting": {}, "characters": [], "visual_beats": [], "props": [], "environment_effects": [], "time_of_day": ""},
            ]},
            # 角色注册解析
            {"characters": [{"character_id": "character_1", "display_name": "少女"}]},
            # 风格分析解析
            {"summary": {"overall_style_description": "写实风格的日常Vlog"}},
            # 导演分析解析
            {"video_type": "Vlog", "visual_style": {"cinematography": "纪实风格"}},
            # 提示词反推解析
            {"global_prompt": {"style": "纪实日常风格"}, "shot_prompts": []},
        ],
    )

    # Mock DB
    mock_db = MagicMock()
    mock_db.refresh = MagicMock(side_effect=lambda obj: setattr(obj, "id", 42))
    mocker.patch("services.video_reverse_engineer.SessionLocal", return_value=mock_db)

    # Mock 配置读取
    mocker.patch("services.video_reverse_engineer._configure_visual_api", return_value=None)

    workflow_id = asyncio.run(
        analyze_video(
            video_path="/tmp/test.mp4",
            story_id=1,
            chapter_id=None,
            user_id=1,
        )
    )

    assert workflow_id is not None
    assert workflow_id == 42
    assert mock_db.commit.called
    from models import ChapterVideoWorkflow, ChapterVideoShot, VideoRemix
    add_calls = mock_db.add.call_args_list
    workflow_obj = None
    for call in add_calls:
        obj = call[0][0]
        if isinstance(obj, ChapterVideoWorkflow):
            workflow_obj = obj
            break
    assert workflow_obj is not None, "ChapterVideoWorkflow was not created"
    assert workflow_obj.total_shots == 2
    # V3 字段
    assert workflow_obj.observation_json is not None
    assert workflow_obj.character_registry_json is not None
    assert workflow_obj.style_analysis_json is not None
    assert workflow_obj.director_analysis_json is not None
    assert workflow_obj.prompt_reverse_json is not None
    assert workflow_obj.observation_raw_text is not None


def test_analyze_video_direct_vlm_fails(mocker):
    """VLM 视频分析失败时应抛出异常。"""
    from services.video_reverse_engineer import analyze_video

    mock_subprocess = mocker.patch("services.video_reverse_engineer.subprocess.run")
    mock_result = MagicMock()
    mock_result.stdout = "5.8\n"
    mock_subprocess.return_value = mock_result

    mocker.patch(
        "services.visual_api.analyze_video_direct",
        side_effect=UpstreamServiceError("API 不支持视频格式", retryable=False, provider="Visual", status_code=415),
    )
    mocker.patch("services.video_reverse_engineer._configure_visual_api", return_value=None)

    with pytest.raises(ValueError):
        asyncio.run(
            analyze_video(
                video_path="/tmp/test.mp4",
                story_id=1,
                chapter_id=None,
                user_id=1,
            )
        )
