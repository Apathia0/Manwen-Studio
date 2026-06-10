import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ChapterVideoShot, ChapterVideoWorkflow
from services import deepseek
from services import video_chapter_pipeline
from services.video_chapter_prompts import build_shot_parse_user_prompt


@pytest.fixture
def workflow_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", Session)

    session = Session()
    workflow = ChapterVideoWorkflow(
        chapter_id=12,
        story_id=34,
        source_text="正文",
        workflow_status="pending",
        character_reference_ids=[101, 202],
        video_style="写实电影感",
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    session.close()

    yield Session, workflow.id


def test_build_shot_parse_user_prompt_includes_director_rules():
    prompt = build_shot_parse_user_prompt("主角推门走进旧宅，听见楼上传来脚步声。")

    assert "叙事完整优先" in prompt
    assert "次要内容并入相邻关键镜头" in prompt
    assert "角色参考图优先" in prompt
    assert "心理描写转译为可拍画面" in prompt
    assert "电影感" in prompt
    assert '"storyboard_json"' in prompt
    assert '"visual_focus"' in prompt
    assert '"opening_beat"' in prompt
    assert '"main_beat"' in prompt
    assert '"closing_beat"' in prompt


@pytest.mark.asyncio
async def test_generate_shot_storyboard_prompt_uses_storyboard_json_structure():
    prompt = await deepseek.generate_shot_storyboard_prompt(
        {
            "shot_index": 3,
            "scene_location": "旧宅走廊",
            "time_of_day": "夜",
            "characters": ["林秋"],
            "story_summary": "林秋听见脚步声后停住呼吸",
            "dialogue_or_narration": "她不敢出声。",
            "camera_plan": "中景缓慢推近",
            "motion_plan": "先停步，再抬头看向楼梯",
            "emotion_plan": "压抑逐渐转为警觉",
            "storyboard_json": {
                "visual_focus": "林秋停在走廊中央，抬眼望向黑暗楼梯口",
                "opening_beat": "0-2秒：空荡走廊与轻微脚步回声",
                "main_beat": "2-8秒：林秋屏住呼吸，手指微微收紧，镜头缓慢推近",
                "closing_beat": "8-10秒：她抬眼望向楼梯口，空气压迫感增强",
                "continuity_anchor": "保持白衬衫、黑长发、手中旧钥匙与走廊冷蓝色顶灯一致",
            },
        }
    )

    assert "visual_focus" not in prompt
    assert "林秋停在走廊中央，抬眼望向黑暗楼梯口" in prompt
    assert "0-2秒：空荡走廊与轻微脚步回声" in prompt
    assert "2-8秒：林秋屏住呼吸，手指微微收紧，镜头缓慢推近" in prompt
    assert "8-10秒：她抬眼望向楼梯口，空气压迫感增强" in prompt
    assert "保持白衬衫、黑长发、手中旧钥匙与走廊冷蓝色顶灯一致" in prompt


@pytest.mark.asyncio
async def test_start_workflow_background_passes_api_key(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        "get_workflow",
        lambda workflow_id: SimpleNamespace(
            id=workflow_id,
            chapter_id=12,
            story_id=34,
            source_text="正文",
            character_reference_ids=[9, 10],
            video_style="写实电影感",
        ),
    )

    async def fake_submit_task(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(video_chapter_pipeline.task_manager, "submit_task", fake_submit_task)

    task_id = await video_chapter_pipeline.start_workflow_background(77, api_key="deepseek-test-key")

    assert task_id.startswith("chapter_video_77_")
    assert captured["api_key"] == "deepseek-test-key"
    assert captured["workflow_id"] == 77


def test_save_shots_from_parse_persists_storyboard_json_and_reference_ids(workflow_db):
    Session, workflow_id = workflow_db

    created = video_chapter_pipeline.save_shots_from_parse(
        workflow_id,
        [
            {
                "shot_index": 1,
                "source_text_span": "她停在门口。",
                "scene_location": "旧宅门厅",
                "time_of_day": "夜",
                "characters": ["林秋"],
                "story_summary": "林秋停下脚步",
                "dialogue_or_narration": "她没有继续往前。",
                "camera_plan": "中景，缓慢推近",
                "motion_plan": "停步，抬眼",
                "emotion_plan": "迟疑转为警觉",
                "continuity_notes": "保持白衬衫与旧钥匙",
                "storyboard_json": {
                    "visual_focus": "林秋站在门厅正中望向黑暗深处",
                    "main_beat": "2-8秒镜头缓慢推近，突出呼吸停顿",
                },
                "character_reference_ids": [101, 202],
            }
        ],
    )

    assert len(created) == 1

    session = Session()
    try:
        shot = session.query(ChapterVideoShot).filter_by(workflow_id=workflow_id, shot_index=1).one()
        assert shot.storyboard_json == {
            "visual_focus": "林秋站在门厅正中望向黑暗深处",
            "main_beat": "2-8秒镜头缓慢推近，突出呼吸停顿",
        }
        assert shot.character_reference_ids == [101, 202]
    finally:
        session.close()


def test_chapter_video_workflow_supports_stage_statuses():
    """验证 workflow_status 列长度足以存储所有分阶段状态值。"""
    workflow_status_length = ChapterVideoWorkflow.__table__.c.workflow_status.type.length
    expected = [
        'pending',
        'parsing_shots',
        'shots_ready',
        'generating_storyboards',
        'storyboards_ready',
        'generating_videos',
        'videos_ready',
        'completed',
        'failed',
    ]
    assert workflow_status_length >= max(len(item) for item in expected), \
        f"workflow_status 长度 {workflow_status_length} 不足以存储 {expected}"


def test_chapter_video_shot_status_supports_manual_stage_values():
    """验证 shot status 列长度足以存储所有手动阶段值。"""
    shot_status_length = ChapterVideoShot.__table__.c.status.type.length
    expected = [
        'pending',
        'storyboard_generating',
        'storyboard_ready',
        'video_generating',
        'video_ready',
        'failed',
    ]
    assert shot_status_length >= max(len(item) for item in expected), \
        f"shot status 长度 {shot_status_length} 不足以存储 {expected}"


def test_chapter_workflow_stage_action_schema_exists():
    """验证分阶段操作请求 schema 已定义（TDD 红线：此测试应先失败）。"""
    from schemas import (
        ChapterWorkflowStageActionRequest,
        ChapterWorkflowPromptReanalyzeRequest,
    )

    # 验证 ChapterWorkflowStageActionRequest 结构
    req = ChapterWorkflowStageActionRequest()
    assert req.shot_ids == []
    assert req.run_all is False
    assert req.auto_continue is False

    # 验证带 shot_ids 的初始化
    req2 = ChapterWorkflowStageActionRequest(shot_ids=[1, 2, 3], run_all=True)
    assert req2.shot_ids == [1, 2, 3]
    assert req2.run_all is True

    # 验证 ChapterWorkflowPromptReanalyzeRequest
    reanalyze_req = ChapterWorkflowPromptReanalyzeRequest(shot_ids=[1])
    assert reanalyze_req.shot_ids == [1]
    assert ChapterWorkflowPromptReanalyzeRequest().shot_ids == []


def test_storyboard_static_url_strips_manga_outputs_prefix():
    url = video_chapter_pipeline._to_storyboard_static_url(
        'manga_outputs/chapter_440/panel_1006_171e246d.png'
    )

    assert url == '/static/manga/chapter_440/panel_1006_171e246d.png'


@pytest.mark.asyncio
async def test_reanalyze_shot_prompts_returns_character_prompts_from_story_versions(workflow_db, monkeypatch):
    Session, workflow_id = workflow_db

    session = Session()
    try:
        from models import Story, StoryCharacterVersion

        story = Story(id=34, title='测试作品', character_profiles='林秋：黑发白衬衫。')
        session.add(story)
        session.commit()

        version = StoryCharacterVersion(
            story_id=34,
            character_name='林秋',
            version_label='v1-默认',
            appearance_card='林秋角色设定卡',
            is_default=True,
        )
        session.add(version)
        session.commit()

        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停下脚步',
            dialogue_or_narration='她没有出声。',
            camera_plan='中景缓慢推近',
            motion_plan='停步后抬眼',
            emotion_plan='压抑转警觉',
            continuity_notes='保持白衬衫与旧钥匙',
            storyboard_prompt='旧提示词',
            video_prompt='旧视频提示词',
            status='pending',
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)
        shot_id = shot.id
    finally:
        session.close()

    async def fake_storyboard_prompt(payload):
        return f"故事版:{payload['story_summary']}"

    async def fake_video_prompt(payload):
        return f"视频:{payload['motion_plan']}"

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt', fake_video_prompt)

    result = await video_chapter_pipeline.reanalyze_shot_prompts(shot_id)

    assert result['shot_id'] == shot_id
    assert result['storyboard_prompt'] == '故事版:林秋停下脚步'
    assert result['video_prompt'] == '视频:停步后抬眼'
    assert result['character_prompts'] == [
        {'name': '林秋', 'prompt': '林秋角色设定卡'}
    ]
