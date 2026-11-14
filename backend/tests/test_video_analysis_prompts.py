"""测试视频分析 Prompt 模板。"""

from prompts.video_analysis import (
    VIDEO_ANALYSIS_SYSTEM_PROMPT,
    build_video_analysis_user_prompt,
)


def test_system_prompt_is_not_empty():
    """系统提示词应包含详细的分析指令。"""
    assert len(VIDEO_ANALYSIS_SYSTEM_PROMPT) > 100


def test_build_user_prompt_contains_frame_info():
    """构建的用户提示词应包含帧数和时长信息。"""
    prompt = build_video_analysis_user_prompt(
        frame_count=20, frame_interval=3.0, total_duration=60
    )
    assert "20" in prompt
    assert "3.0" in prompt
    assert "60" in prompt
    assert "关键帧序列" in prompt
    assert "JSON" in prompt
