import asyncio
import json
from types import SimpleNamespace

import httpx

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ChapterVideoShot, ChapterVideoWorkflow
from services import deepseek
from services import video_chapter_pipeline
from services.video_chapter_prompts import build_shot_parse_lite_user_prompt, build_shot_parse_user_prompt


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

    assert "用最少数量的分镜，讲最完整的故事" in prompt
    assert "同一时间、同一地点、同一事件链、同一目标、同一情绪线的内容必须合并" in prompt
    assert "角色参考图优先" in prompt
    assert "心理描写必须转译为可拍画面" in prompt
    assert "一个合格分镜至少承担以下两项中的两项以上" in prompt
    assert '"storyboard_json"' in prompt
    assert '"visual_focus"' in prompt
    assert '"segments"' in prompt
    assert '"story_task"' in prompt
    assert '"rhythm_function"' in prompt
    assert '"key_props"' in prompt
    assert '"scene_asset_candidates"' in prompt


def test_build_shot_parse_lite_user_prompt_uses_event_based_rules():
    prompt = build_shot_parse_lite_user_prompt('主角推门走进旧宅，听见楼上传来脚步声。')

    assert '你的职责不是拆镜头' in prompt
    assert '把故事变成事件' in prompt
    assert '禁止根据字数决定分镜数量' in prompt
    assert '如果一个分镜无法在15秒内完成事件开始、发展、结果与情绪变化，必须继续拆分' in prompt
    assert '不输出运镜、景别、构图、摄影机参数' in prompt


def test_build_shot_parse_lite_user_prompt_mentions_short_drama_pacing_cap():
    prompt = build_shot_parse_lite_user_prompt('主角推门走进旧宅，听见楼上传来脚步声。')

    assert '如果分镜数量明显超过剧情关键事件数量，必须回退并合并' in prompt
    assert '同一场景内连续反应、连续动作、连续信息揭示优先并入前一分镜' in prompt


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
            "source_text_span": "林晚晚正对着电脑屏幕上的Excel表格头疼。顾深发来一条微信",
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
    assert "顾深发来一条微信" in prompt

    # 不传 source_text_span 时使用默认文案
    prompt_no_span = await deepseek.generate_shot_storyboard_prompt(
        {
            "shot_index": 1,
            "scene_location": "旧宅门厅",
            "time_of_day": "夜",
            "characters": ["林秋"],
            "story_summary": "林秋停下脚步。",
            "dialogue_or_narration": "她没有继续往前。",
        }
    )
    assert "（无原文片段）" in prompt_no_span


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
                "key_props": ["旧钥匙", "铜钟"],
                "scene_asset_candidates": ["旧宅门厅"],
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
        assert shot.key_props_json == ["旧钥匙", "铜钟"]
        assert shot.scene_asset_candidates_json == ["旧宅门厅"]
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


def test_save_shots_from_parse_rejects_incomplete_skeleton(workflow_db):
    _, workflow_id = workflow_db

    with pytest.raises(ValueError):
        video_chapter_pipeline.save_shots_from_parse(
            workflow_id,
            [
                {
                    'shot_index': 1,
                    'source_text_span': '',
                    'scene_location': '旧宅门厅',
                    'time_of_day': '夜',
                    'characters': ['林秋'],
                    'story_summary': '',
                    'dialogue_or_narration': '她没有继续往前。',
                }
            ],
        )


@pytest.mark.asyncio
async def test_parse_chapter_shots_replaces_existing_shots(workflow_db, monkeypatch):
    Session, workflow_id = workflow_db

    session = Session()
    try:
        session.add(ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=99,
            source_text_span='旧镜头',
            story_summary='旧摘要',
            status='pending',
        ))
        session.commit()
    finally:
        session.close()

    async def fake_parse(**kwargs):
        return [{
            'shot_index': 1,
            'source_text_span': '新镜头。',
            'scene_location': '客厅',
            'time_of_day': '夜',
            'characters': ['林秋'],
            'story_summary': '新摘要',
            'dialogue_or_narration': '她没有继续向前。',
        }]

    async def fake_expand(**kwargs):
        return {'workflow_status': 'shots_ready', 'expanded_shot_count': 1, 'failed_shot_ids': []}

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'parse_chapter_to_shots_lite', fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, 'expand_shots_with_role_prompts', fake_expand)

    await video_chapter_pipeline.parse_chapter_shots(
        workflow_id=workflow_id,
        chapter_id=12,
        story_id=34,
        source_text='正文',
        deepseek_api_key='test-ds-key',
    )

    session = Session()
    try:
        shots = session.query(ChapterVideoShot).filter_by(workflow_id=workflow_id).order_by(ChapterVideoShot.shot_index).all()
        assert len(shots) == 1
        assert shots[0].shot_index == 1
        assert shots[0].source_text_span == '新镜头。'
    finally:
        session.close()


@pytest.mark.asyncio
async def test_run_all_stages_expands_prompts_before_storyboards(monkeypatch):
    call_order: list[str] = []

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(
            id=workflow_id,
            workflow_status='pending',
            total_shots=1,
            completed_shots=1,
            failed_shots=0,
            chapter_id=12,
            story_id=34,
            source_text='正文',
            character_reference_ids=[9],
            video_style='写实电影感',
        ),
    )

    async def fake_parse(**kwargs):
        call_order.append('parse')
        return {'workflow_status': 'shots_ready', 'shot_count': 1, 'total_shots': 1}

    async def fake_expand(**kwargs):
        call_order.append('expand')
        return {'workflow_status': 'prompts_ready', 'expanded_shot_count': 1, 'failed_shot_ids': []}

    async def fake_storyboards(**kwargs):
        call_order.append('storyboard')
        return {'workflow_status': 'storyboards_ready', 'shot_count': 1, 'failed_shot_ids': []}

    async def fake_videos(**kwargs):
        call_order.append('video')
        return {'workflow_status': 'videos_ready', 'shot_count': 1, 'failed_shot_ids': []}

    monkeypatch.setattr(video_chapter_pipeline, 'parse_chapter_shots', fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, 'expand_shots_with_role_prompts', fake_expand)
    monkeypatch.setattr(video_chapter_pipeline, 'generate_storyboards_for_shots', fake_storyboards)
    monkeypatch.setattr(video_chapter_pipeline, 'generate_videos_for_shots', fake_videos)
    monkeypatch.setattr(video_chapter_pipeline, 'update_workflow_status', lambda *args, **kwargs: None)

    result = await video_chapter_pipeline.run_all_stages(
        workflow_id=77,
        chapter_id=12,
        story_id=34,
        source_text='正文',
        deepseek_api_key='test-ds-key',
        image_api_key='test-img-key',
    )

    assert result['workflow_status'] == 'completed'
    assert call_order == ['parse', 'expand', 'storyboard', 'video']


@pytest.mark.asyncio
async def test_run_all_stages_logs_stage_integrity(monkeypatch, caplog):
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(
            id=workflow_id,
            workflow_status='pending',
            total_shots=1,
            completed_shots=1,
            failed_shots=0,
            chapter_id=12,
            story_id=34,
            source_text='正文',
            character_reference_ids=[9],
            video_style='写实电影感',
        ),
    )

    async def fake_parse(**kwargs):
        return {'workflow_status': 'shots_ready', 'shot_count': 1, 'total_shots': 1}

    async def fake_expand(**kwargs):
        return {'workflow_status': 'shots_ready', 'expanded_shot_count': 1, 'failed_shot_ids': []}

    async def fake_storyboards(**kwargs):
        return {'workflow_status': 'storyboards_ready', 'shot_count': 1, 'failed_shot_ids': []}

    async def fake_videos(**kwargs):
        return {'workflow_status': 'videos_ready', 'shot_count': 1, 'failed_shot_ids': []}

    monkeypatch.setattr(video_chapter_pipeline, 'parse_chapter_shots', fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, 'expand_shots_with_role_prompts', fake_expand)
    monkeypatch.setattr(video_chapter_pipeline, 'generate_storyboards_for_shots', fake_storyboards)
    monkeypatch.setattr(video_chapter_pipeline, 'generate_videos_for_shots', fake_videos)
    monkeypatch.setattr(video_chapter_pipeline, 'update_workflow_status', lambda *args, **kwargs: None)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        await video_chapter_pipeline.run_all_stages(
            workflow_id=77,
            chapter_id=12,
            story_id=34,
            source_text='正文',
            deepseek_api_key='test-ds-key',
            image_api_key='test-img-key',
        )

    assert '流程完整性 workflow=77 stage=parse result=shots_ready' in caplog.text
    assert '流程完整性 workflow=77 stage=expand result=shots_ready' in caplog.text
    assert '流程完整性 workflow=77 stage=storyboard result=storyboards_ready' in caplog.text
    assert '流程完整性 workflow=77 stage=video result=videos_ready' in caplog.text


@pytest.mark.asyncio
async def test_parse_chapter_shots_runs_prompt_expansion_by_default(monkeypatch):
    calls: list[str] = []

    async def fake_parse(**kwargs):
        calls.append('parse-lite')
        return [{
            'shot_index': 1,
            'source_text_span': '她停下脚步。',
            'scene_location': '客厅',
            'time_of_day': '夜',
            'characters': ['林秋'],
            'story_summary': '她停下脚步',
            'dialogue_or_narration': '她没有继续向前。',
        }]

    async def fake_expand(**kwargs):
        calls.append('expand')
        return {'workflow_status': 'shots_ready', 'expanded_shot_count': 1, 'failed_shot_ids': []}

    monkeypatch.setattr(video_chapter_pipeline, '_load_character_profiles', lambda story_id: '')
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'parse_chapter_to_shots_lite', fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, 'expand_shots_with_role_prompts', fake_expand)
    monkeypatch.setattr(video_chapter_pipeline, 'save_shots_from_parse', lambda workflow_id, shots_data: [SimpleNamespace(id=1)])
    monkeypatch.setattr(video_chapter_pipeline, 'update_workflow_status', lambda *args, **kwargs: None)

    result = await video_chapter_pipeline.parse_chapter_shots(
        workflow_id=11,
        chapter_id=22,
        story_id=33,
        source_text='正文',
        deepseek_api_key='test-ds-key',
    )

    assert result['workflow_status'] == 'shots_ready'
    assert result['expanded_shot_count'] == 1
    assert calls == ['parse-lite', 'expand']


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_reuses_character_prompts_from_story_versions(workflow_db, monkeypatch):
    Session, workflow_id = workflow_db
    from models import Story, StoryCharacterVersion

    session = Session()
    try:
        story = Story(id=34, title='测试作品', character_profiles='林秋：黑发白衬衫。')
        session.add(story)
        session.add(StoryCharacterVersion(
            story_id=34,
            character_name='林秋',
            version_label='v1-默认',
            appearance_card='林秋角色设定卡',
            is_default=True,
        ))
        session.add_all([
            ChapterVideoShot(
                workflow_id=workflow_id, shot_index=1, source_text_span='一', scene_location='旧宅', time_of_day='夜',
                characters=['林秋'], story_summary='林秋停下脚步', dialogue_or_narration='她没有出声。', status='pending'
            ),
            ChapterVideoShot(
                workflow_id=workflow_id, shot_index=2, source_text_span='二', scene_location='旧宅', time_of_day='夜',
                characters=['林秋'], story_summary='林秋抬头看向楼梯', dialogue_or_narration='她听见脚步。', status='pending'
            ),
        ])
        session.commit()
    finally:
        session.close()

    calls = {'character_ai': 0}

    async def fake_generate_shot_details(**kwargs):
        return [{
            'shot_index': kwargs['shots_basic_info'][0]['shot_index'],
            'camera_plan': '中景', 'motion_plan': '停步', 'emotion_plan': '警觉',
            'continuity_notes': '保持服装一致', 'storyboard_json': {'visual_focus': '林秋'}
        }]

    async def fake_storyboard_prompt(*args, **kwargs):
        return '故事版提示词'

    async def fake_character_prompts_ai(**kwargs):
        calls['character_ai'] += 1
        return [{'name': '林秋', 'prompt': 'AI角色提示词'}]

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ('场景提示词', [])

    async def fake_video_prompt_ai(*args, **kwargs):
        return '视频提示词'

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)

    result = await video_chapter_pipeline.expand_shots_with_role_prompts(
        workflow_id=workflow_id,
        story_id=34,
        deepseek_api_key='test-ds-key',
    )

    assert result['expanded_shot_count'] == 2
    assert calls['character_ai'] == 0


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_reuses_scene_prop_analysis_for_same_scene(workflow_db, monkeypatch):
    Session, workflow_id = workflow_db

    session = Session()
    try:
        session.add_all([
            ChapterVideoShot(
                workflow_id=workflow_id, shot_index=1, source_text_span='一', scene_location='天桥', time_of_day='夜',
                characters=['林晚晚'], story_summary='林晚晚站在天桥上', dialogue_or_narration='风很大。',
                key_props_json=['铜钟'], scene_asset_candidates_json=['天桥'], status='pending'
            ),
            ChapterVideoShot(
                workflow_id=workflow_id, shot_index=2, source_text_span='二', scene_location='天桥', time_of_day='夜',
                characters=['林晚晚'], story_summary='林晚晚再次看向栏杆', dialogue_or_narration='月亮很圆。',
                key_props_json=['铜钟'], scene_asset_candidates_json=['天桥'], status='pending'
            ),
        ])
        session.commit()
    finally:
        session.close()

    calls = {'scene_prop': 0}

    async def fake_generate_shot_details(**kwargs):
        return [{
            'shot_index': kwargs['shots_basic_info'][0]['shot_index'],
            'camera_plan': '中景', 'motion_plan': '停步', 'emotion_plan': '警觉',
            'continuity_notes': '保持铜钟一致', 'storyboard_json': {'visual_focus': '天桥'}
        }]

    async def fake_storyboard_prompt(*args, **kwargs):
        return '故事版提示词'

    async def fake_scene_prop_prompts(*args, **kwargs):
        calls['scene_prop'] += 1
        return ('天桥场景提示词', [{'name': '铜钟', 'prompt': '铜钟道具提示词'}])

    async def fake_video_prompt_ai(*args, **kwargs):
        return '视频提示词'

    async def fake_character_prompts_ai(**kwargs):
        return [{'name': '林晚晚', 'prompt': '角色提示词'}]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)

    result = await video_chapter_pipeline.expand_shots_with_role_prompts(
        workflow_id=workflow_id,
        story_id=34,
        deepseek_api_key='test-ds-key',
    )

    assert result['expanded_shot_count'] == 2
    assert calls['scene_prop'] == 1


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

    async def fake_storyboard_prompt(payload, **kwargs):
        return f"故事版:{payload['story_summary']}"

    async def fake_video_prompt_ai(shot_data, **kwargs):
        return f"视频:{shot_data['motion_plan']}"

    async def fake_character_prompts(**kwargs):
        return [{"name": "林秋", "prompt": "林秋角色设定卡"}]

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ("场景提示词", [])

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

    result = await video_chapter_pipeline.reanalyze_shot_prompts(shot_id)

    assert result['shot_id'] == shot_id
    assert result['storyboard_prompt'] == '故事版:林秋停下脚步'
    assert result['video_prompt'] == '视频:停步后抬眼'
    assert result['character_prompts'] == [
        {'name': '林秋', 'prompt': '林秋角色设定卡'}
    ]


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_logs_summary(workflow_db, monkeypatch, caplog):
    Session, workflow_id = workflow_db

    session = Session()
    try:
        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            source_text_span='她停下脚步。',
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停下脚步',
            dialogue_or_narration='她没有出声。',
            status='pending',
        )
        session.add(shot)
        session.commit()
    finally:
        session.close()

    async def fake_expand_single(shot_id, **kwargs):
        return {'shot_id': shot_id, 'storyboard_prompt': '故事版', 'video_prompt': '视频'}

    monkeypatch.setattr(video_chapter_pipeline, '_expand_single_shot_prompts', fake_expand_single)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        result = await video_chapter_pipeline.expand_shots_with_role_prompts(
            workflow_id=workflow_id,
            story_id=34,
            deepseek_api_key='test-ds-key',
        )

    assert result['expanded_shot_count'] == 1
    assert '阶段1.5-提示词补全 workflow=' in caplog.text
    assert '提示词补全完成 workflow=' in caplog.text


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_logs_scene_prop_cache_hit(workflow_db, monkeypatch, caplog):
    Session, workflow_id = workflow_db

    session = Session()
    try:
        session.add_all([
            ChapterVideoShot(
                workflow_id=workflow_id, shot_index=1, source_text_span='一', scene_location='天桥', time_of_day='夜',
                characters=['林晚晚'], story_summary='林晚晚站在天桥上', dialogue_or_narration='风很大。',
                key_props_json=['铜钟'], scene_asset_candidates_json=['天桥'], status='pending'
            ),
            ChapterVideoShot(
                workflow_id=workflow_id, shot_index=2, source_text_span='二', scene_location='天桥', time_of_day='夜',
                characters=['林晚晚'], story_summary='林晚晚再次看向栏杆', dialogue_or_narration='月亮很圆。',
                key_props_json=['铜钟'], scene_asset_candidates_json=['天桥'], status='pending'
            ),
        ])
        session.commit()
    finally:
        session.close()

    async def fake_generate_shot_details(**kwargs):
        return [{
            'shot_index': kwargs['shots_basic_info'][0]['shot_index'],
            'camera_plan': '中景', 'motion_plan': '停步', 'emotion_plan': '警觉',
            'continuity_notes': '保持铜钟一致', 'storyboard_json': {'visual_focus': '天桥'}
        }]

    async def fake_storyboard_prompt(*args, **kwargs):
        return '故事版提示词'

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ('天桥场景提示词', [{'name': '铜钟', 'prompt': '铜钟道具提示词'}])

    async def fake_video_prompt_ai(*args, **kwargs):
        return '视频提示词'

    async def fake_character_prompts_ai(**kwargs):
        return [{'name': '林晚晚', 'prompt': '角色提示词'}]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        result = await video_chapter_pipeline.expand_shots_with_role_prompts(
            workflow_id=workflow_id,
            story_id=34,
            deepseek_api_key='test-ds-key',
        )

    assert result['expanded_shot_count'] == 2
    assert 'scene_prop cache miss' in caplog.text
    assert 'scene_prop cache hit' in caplog.text


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_logs_character_prompt_source(workflow_db, monkeypatch, caplog):
    Session, workflow_id = workflow_db
    from models import Story, StoryCharacterVersion

    session = Session()
    try:
        story = Story(id=34, title='测试作品', character_profiles='林秋：黑发白衬衫。')
        session.add(story)
        session.add(StoryCharacterVersion(
            story_id=34,
            character_name='林秋',
            version_label='v1-默认',
            appearance_card='林秋角色设定卡',
            is_default=True,
        ))
        session.add(ChapterVideoShot(
            workflow_id=workflow_id, shot_index=1, source_text_span='一', scene_location='旧宅', time_of_day='夜',
            characters=['林秋'], story_summary='林秋停下脚步', dialogue_or_narration='她没有出声。', status='pending'
        ))
        session.commit()
    finally:
        session.close()

    async def fake_generate_shot_details(**kwargs):
        return [{
            'shot_index': kwargs['shots_basic_info'][0]['shot_index'],
            'camera_plan': '中景', 'motion_plan': '停步', 'emotion_plan': '警觉',
            'continuity_notes': '保持服装一致', 'storyboard_json': {'visual_focus': '林秋'}
        }]

    async def fake_storyboard_prompt(*args, **kwargs):
        return '故事版提示词'

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ('场景提示词', [])

    async def fake_video_prompt_ai(*args, **kwargs):
        return '视频提示词'

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        result = await video_chapter_pipeline.expand_shots_with_role_prompts(
            workflow_id=workflow_id,
            story_id=34,
            deepseek_api_key='test-ds-key',
        )

    assert result['expanded_shot_count'] == 1
    assert 'character prompts reused' in caplog.text


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_falls_back_to_ai_for_generic_supporting_roles(workflow_db, monkeypatch):
    Session, workflow_id = workflow_db
    from models import Story, StoryCharacterVersion

    session = Session()
    try:
        story = Story(id=34, title='测试作品', character_profiles='林秋：黑发白衬衫。')
        session.add(story)
        session.add(StoryCharacterVersion(
            story_id=34,
            character_name='林秋',
            version_label='v1-默认',
            appearance_card='林秋角色设定卡',
            is_default=True,
        ))
        session.add(ChapterVideoShot(
            workflow_id=workflow_id, shot_index=1, source_text_span='一', scene_location='医院走廊', time_of_day='白天',
            characters=['林秋', '护士'], story_summary='林秋在医院见到护士', dialogue_or_narration='护士让开了路。', status='pending'
        ))
        session.commit()
    finally:
        session.close()

    calls = {'character_ai': 0}

    async def fake_generate_shot_details(**kwargs):
        return [{
            'shot_index': kwargs['shots_basic_info'][0]['shot_index'],
            'camera_plan': '中景', 'motion_plan': '停步', 'emotion_plan': '警觉',
            'continuity_notes': '保持服装一致', 'storyboard_json': {'visual_focus': '医院走廊'}
        }]

    async def fake_storyboard_prompt(*args, **kwargs):
        return '故事版提示词'

    async def fake_character_prompts_ai(**kwargs):
        calls['character_ai'] += 1
        assert kwargs['shot_data']['characters'] == ['护士']
        return [{'name': '护士', 'prompt': '护士角色提示词'}]

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ('场景提示词', [])

    async def fake_video_prompt_ai(*args, **kwargs):
        return '视频提示词'

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)

    result = await video_chapter_pipeline.expand_shots_with_role_prompts(
        workflow_id=workflow_id,
        story_id=34,
        deepseek_api_key='test-ds-key',
    )

    assert result['expanded_shot_count'] == 1
    assert calls['character_ai'] == 1

    session = Session()
    try:
        shot = session.query(ChapterVideoShot).filter_by(workflow_id=workflow_id, shot_index=1).one()
        assert shot.character_prompts_json == [
            {'name': '林秋', 'prompt': '林秋角色设定卡'},
            {'name': '护士', 'prompt': '护士角色提示词'},
        ]
    finally:
        session.close()


# ── Bug: JSON 数组而非 {"shots": [...]} ──────────────────────


def test_json_array_bypasses_all_repair_mechanisms():
    """验证：合法 JSON 数组不被 _repair_broken_json_fields /
    _repair_truncated_json 修复，_extract_json_object 抛 ValueError。"""
    shots = [
        {"shot_index": 1, "scene_location": "办公室", "story_summary": "开会"},
        {"shot_index": 2, "scene_location": "走廊", "story_summary": "交谈"},
    ]
    content = json.dumps(shots)

    with pytest.raises(ValueError, match="not an object"):
        deepseek._extract_json_object(content)

    repaired = deepseek._repair_broken_json_fields(content)
    assert repaired == content

    truncated = deepseek._repair_truncated_json(content)
    assert truncated == content


@pytest.mark.asyncio
async def test_parse_lite_chunk_accepts_json_array(monkeypatch):
    """_parse_lite_chunk 应兼容 DeepSeek 直接返回 JSON 数组。"""
    shots_data = [
        {
            "shot_index": 1,
            "source_text_span": "林晚晚加班",
            "scene_location": "办公室",
            "time_of_day": "夜晚",
            "characters": ["林晚晚"],
            "story_summary": "加班中收到邀请",
            "dialogue_or_narration": "手机亮了一下。",
            "key_props": ["手机"],
            "scene_asset_candidates": ["办公室"],
        },
        {
            "shot_index": 2,
            "source_text_span": "回复邀请",
            "scene_location": "办公室",
            "time_of_day": "夜晚",
            "characters": ["林晚晚"],
            "story_summary": "她犹豫了一下还是点开了消息。",
            "dialogue_or_narration": "她犹豫了一下，还是点开了。",
            "key_props": ["手机"],
            "scene_asset_candidates": ["办公室"],
        },
    ]
    response_content = json.dumps(shots_data)

    class FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": response_content}}]}

    original_post = httpx.AsyncClient.post

    async def fake_post(self, *args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    deepseek.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    deepseek.DEEPSEEK_MODEL = "deepseek-chat"

    result = await deepseek._parse_lite_chunk(
        "林晚晚在办公室里加班，手机突然亮了一下……",
        api_key="test-key",
    )

    assert len(result) == 2
    assert result[0]["shot_index"] == 1
    assert result[0]["story_summary"] == "加班中收到邀请"
    assert result[1]["shot_index"] == 2


# ── 跨章节角色提示词复用 ─────────────────────────────


def test_ensure_character_version_creates_new_version(monkeypatch):
    from models import StoryCharacterVersion
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", Session)

    video_chapter_pipeline._ensure_character_version(
        story_id=1, name="林晚晚", prompt="黑色长发，职场女性，气质干练"
    )

    session = Session()
    try:
        versions = session.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == 1,
            StoryCharacterVersion.character_name == "林晚晚",
        ).all()
        assert len(versions) == 1
        assert versions[0].appearance_card == "黑色长发，职场女性，气质干练"
        assert versions[0].is_default is True
    finally:
        session.close()


def test_ensure_character_version_does_not_overwrite_existing_default(monkeypatch):
    from models import StoryCharacterVersion
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", Session)

    session = Session()
    try:
        session.add(StoryCharacterVersion(
            story_id=1, character_name="林晚晚", version_label="v1-默认",
            appearance_card="用户手动创建的版本", is_default=True,
        ))
        session.commit()
    finally:
        session.close()

    video_chapter_pipeline._ensure_character_version(
        story_id=1, name="林晚晚", prompt="AI 生成的新版本"
    )

    session = Session()
    try:
        versions = session.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == 1,
            StoryCharacterVersion.character_name == "林晚晚",
        ).all()
        assert len(versions) == 1
        assert versions[0].appearance_card == "用户手动创建的版本", "不应覆盖用户手动创建的版本"
    finally:
        session.close()


def test_ensure_character_version_skips_on_empty_prompt(monkeypatch):
    from models import StoryCharacterVersion
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", Session)

    video_chapter_pipeline._ensure_character_version(story_id=1, name="", prompt="有内容")
    video_chapter_pipeline._ensure_character_version(story_id=1, name="林晚晚", prompt="")
    video_chapter_pipeline._ensure_character_version(story_id=1, name="  ", prompt="  ")

    session = Session()
    try:
        count = session.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == 1,
        ).count()
        assert count == 0
    finally:
        session.close()


@pytest.mark.asyncio
async def test_expand_shots_saves_ai_character_prompts_to_story_character_version(workflow_db, monkeypatch):
    Session, workflow_id = workflow_db
    from models import Story, StoryCharacterVersion

    session = Session()
    try:
        story = Story(id=34, title='测试作品', character_profiles='')
        session.add(story)
        session.add(ChapterVideoShot(
            workflow_id=workflow_id, shot_index=1,
            source_text_span='一', scene_location='咖啡店', time_of_day='夜',
            characters=['林晚晚'], story_summary='林晚晚走进咖啡店',
            dialogue_or_narration='她推开门。', status='pending'
        ))
        session.commit()
    finally:
        session.close()

    async def fake_generate_shot_details(**kwargs):
        return [{'shot_index': 1, 'camera_plan': '中景', 'motion_plan': '推门', 'emotion_plan': '平静',
                 'continuity_notes': '', 'storyboard_json': {}}]

    async def fake_storyboard_prompt(*args, **kwargs):
        return '故事版提示词'

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ('场景提示词', [])

    async def fake_video_prompt_ai(*args, **kwargs):
        return '视频提示词'

    async def fake_character_prompts_ai(**kwargs):
        return [{'name': '林晚晚', 'prompt': '黑色长发，职场女性，气质干练'}]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_video_prompt_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)

    await video_chapter_pipeline.expand_shots_with_role_prompts(
        workflow_id=workflow_id,
        story_id=34,
        deepseek_api_key='test-ds-key',
    )

    session = Session()
    try:
        version = session.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == 34,
            StoryCharacterVersion.character_name == '林晚晚',
            StoryCharacterVersion.is_default == True,
        ).first()
        assert version is not None, "AI 生成的角色提示词应保存到 StoryCharacterVersion"
        assert version.appearance_card == '黑色长发，职场女性，气质干练'
    finally:
        session.close()
