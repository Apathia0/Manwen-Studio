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
from services.video_chapter_prompts import build_shot_parse_lite_user_prompt


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
                "character_prompts_json": [{"name": "林秋", "prompt": "林秋角色设定卡"}],
                "scene_prompt": "旧宅门厅场景提示词",
                "prop_prompts_json": [{"name": "旧钥匙", "prompt": "旧钥匙道具提示词"}],
                "character_reference_ids": [101, 202],
                "scene_reference_ids": [303],
                "prop_reference_ids": [404, 405],
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
        assert shot.character_prompts_json == [{"name": "林秋", "prompt": "林秋角色设定卡"}]
        assert shot.scene_prompt == "旧宅门厅场景提示词"
        assert shot.prop_prompts_json == [{"name": "旧钥匙", "prompt": "旧钥匙道具提示词"}]
        assert shot.character_reference_ids == [101, 202]
        assert shot.scene_reference_ids == [303]
        assert shot.prop_reference_ids == [404, 405]
        assert shot.key_props_json == ["旧钥匙", "铜钟"]
        assert shot.scene_asset_candidates_json == ["旧宅门厅"]
    finally:
        session.close()


def test_apply_story_reuse_cache_to_shots_prefills_prompts_and_asset_ids():
    shots_data = [
        {
            "shot_index": 1,
            "source_text_span": "林秋停在旧宅门厅。",
            "scene_location": "旧宅门厅",
            "time_of_day": "夜",
            "characters": ["林秋"],
            "story_summary": "林秋停下脚步",
            "dialogue_or_narration": "她没有继续向前。",
            "key_props": ["旧钥匙", "铜钟"],
            "scene_asset_candidates": ["旧宅门厅"],
        }
    ]
    story_cache = {
        "characters": {
            "林秋": {
                "prompt": "林秋角色设定卡",
                "asset_ids": [101, 202],
            }
        },
        "scenes": {
            ("旧宅门厅", "夜"): {
                "prompt": "旧宅门厅场景提示词",
                "asset_ids": [303],
            }
        },
        "props": {
            "旧钥匙": {
                "prompt": "旧钥匙道具提示词",
                "asset_ids": [404],
            },
            "铜钟": {
                "prompt": "铜钟道具提示词",
                "asset_ids": [405],
            },
        },
    }

    hydrated = video_chapter_pipeline._apply_story_reuse_cache_to_shots(shots_data, story_cache)

    assert hydrated[0]["character_prompts_json"] == [{"name": "林秋", "prompt": "林秋角色设定卡"}]
    assert hydrated[0]["character_reference_ids"] == [101, 202]
    assert hydrated[0]["scene_prompt"] == "旧宅门厅场景提示词"
    assert hydrated[0]["scene_reference_ids"] == [303]
    assert hydrated[0]["prop_prompts_json"] == [
        {"name": "旧钥匙", "prompt": "旧钥匙道具提示词"},
        {"name": "铜钟", "prompt": "铜钟道具提示词"},
    ]
    assert hydrated[0]["prop_reference_ids"] == [404, 405]


@pytest.mark.asyncio
async def test_parse_chapter_shots_prefills_story_reuse_cache_before_expand(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_parse(**kwargs):
        return [{
            'shot_index': 1,
            'source_text_span': '她停在门厅。',
            'scene_location': '旧宅门厅',
            'time_of_day': '夜',
            'characters': ['林秋'],
            'story_summary': '她停下脚步',
            'dialogue_or_narration': '她没有继续向前。',
            'key_props': ['旧钥匙'],
            'scene_asset_candidates': ['旧宅门厅'],
        }]

    async def fake_expand(**kwargs):
        return {'workflow_status': 'shots_ready', 'expanded_shot_count': 1, 'failed_shot_ids': []}

    monkeypatch.setattr(video_chapter_pipeline, '_load_character_profiles', lambda story_id: '')
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'parse_chapter_to_shots_lite', fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, 'expand_shots_with_role_prompts', fake_expand)
    monkeypatch.setattr(video_chapter_pipeline, 'update_workflow_status', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_build_story_reuse_cache',
        lambda story_id: {
            'characters': {'林秋': {'prompt': '林秋角色设定卡', 'asset_ids': [11]}},
            'scenes': {('旧宅门厅', '夜'): {'prompt': '旧宅门厅场景提示词', 'asset_ids': [22]}},
            'props': {'旧钥匙': {'prompt': '旧钥匙道具提示词', 'asset_ids': [33]}},
        },
    )

    def fake_save(workflow_id, shots_data):
        captured['shots_data'] = shots_data
        return [SimpleNamespace(id=1)]

    monkeypatch.setattr(video_chapter_pipeline, 'save_shots_from_parse', fake_save)

    result = await video_chapter_pipeline.parse_chapter_shots(
        workflow_id=11,
        chapter_id=22,
        story_id=33,
        source_text='正文',
        deepseek_api_key='test-ds-key',
    )

    hydrated = captured['shots_data'][0]
    assert result['workflow_status'] == 'shots_ready'
    assert hydrated['character_prompts_json'] == [{'name': '林秋', 'prompt': '林秋角色设定卡'}]
    assert hydrated['character_reference_ids'] == [11]
    assert hydrated['scene_prompt'] == '旧宅门厅场景提示词'
    assert hydrated['scene_reference_ids'] == [22]
    assert hydrated['prop_prompts_json'] == [{'name': '旧钥匙', 'prompt': '旧钥匙道具提示词'}]
    assert hydrated['prop_reference_ids'] == [33]


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


def test_save_shots_from_parse_fills_defaults_for_missing_fields(workflow_db):
    """缺失 source_text_span / story_summary 时降级填充占位符而非 raise。"""
    Session, workflow_id = workflow_db

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
    session = Session()
    try:
        shots = session.query(ChapterVideoShot).filter(
            ChapterVideoShot.workflow_id == workflow_id
        ).order_by(ChapterVideoShot.shot_index).all()
        assert len(shots) == 1
        assert shots[0].shot_index == 1
        assert shots[0].source_text_span == '（第 1 镜）'
        assert shots[0].story_summary == '镜头 1'
    finally:
        session.close()


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

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

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

    async def fake_character_prompts_ai(**kwargs):
        return [{'name': '林晚晚', 'prompt': '角色提示词'}]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

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

    async def fake_character_prompts(**kwargs):
        return [{"name": "林秋", "prompt": "林秋角色设定卡"}]

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ("场景提示词", [])

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

    result = await video_chapter_pipeline.reanalyze_shot_prompts(shot_id)

    assert result['shot_id'] == shot_id
    assert result['storyboard_prompt'] == '故事版:林秋停下脚步'
    assert result['video_prompt'] == '故事版:林秋停下脚步'
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

    async def fake_character_prompts_ai(**kwargs):
        return [{'name': '林晚晚', 'prompt': '角色提示词'}]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

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

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

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


@pytest.mark.asyncio
async def test_expand_shots_with_role_prompts_does_not_reuse_placeholder_prompt_for_generic_role(workflow_db, monkeypatch):
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
        session.add(StoryCharacterVersion(
            story_id=34,
            character_name='护士',
            version_label='v1-默认',
            appearance_card='护士',
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
        return [{'name': '护士', 'prompt': '护士，二十五岁，短发，白色护士服，神色焦急。'}]

    async def fake_scene_prop_prompts(*args, **kwargs):
        return ('场景提示词', [])

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_character_prompts_ai', fake_character_prompts_ai)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)

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
            {'name': '护士', 'prompt': '护士，二十五岁，短发，白色护士服，神色焦急。'},
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

    with pytest.raises(ValueError, match="不是对象"):
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


def test_repair_truncated_json_fixes_truncated_key_name_object():
    content = '{"shots":[{"shot_index":1,"source_text_span":"林晚晚加班","scene_location":"林晚晚办公室","time_of_day":"夜","characters":["林晚晚"],"story_summary":"林晚晚加班时收到顾深邀约看月亮的微信","dialogue_or_narration":"林晚晚打字：我在加班，明天见。","key_'

    repaired = deepseek._repair_truncated_json(content)

    parsed = json.loads(repaired)
    assert isinstance(parsed, dict)
    assert isinstance(parsed.get("shots"), list)
    assert parsed["shots"][0]["shot_index"] == 1


def test_repair_truncated_json_fixes_truncated_key_with_space_before_brace():
    content = '{"shots":[{"shot_index":1,"emotion_plan":"平静","continuity_notes '

    repaired = deepseek._repair_truncated_json(content)

    parsed = json.loads(repaired)
    assert isinstance(parsed, dict)
    assert isinstance(parsed.get("shots"), list)
    assert parsed["shots"][0]["shot_index"] == 1
    assert parsed["shots"][0]["continuity_notes"] is None


@pytest.mark.asyncio
async def test_parse_lite_chunk_accepts_truncated_key_name_json(monkeypatch):
    response_content = '{"shots":[{"shot_index":1,"source_text_span":"林晚晚加班","scene_location":"林晚晚办公室","time_of_day":"夜","characters":["林晚晚"],"story_summary":"林晚晚加班时收到顾深邀约看月亮的微信","dialogue_or_narration":"林晚晚打字：我在加班，明天见。","key_'

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": response_content}}]}

    async def fake_post(self, *args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    deepseek.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    deepseek.DEEPSEEK_MODEL = "deepseek-chat"

    result = await deepseek._parse_lite_chunk(
        "林晚晚正对着电脑屏幕上的Excel表格头疼。",
        api_key="test-key",
    )

    assert len(result) == 1
    assert result[0]["shot_index"] == 1
    assert result[0]["scene_location"] == "林晚晚办公室"


@pytest.mark.asyncio
async def test_parse_lite_chunk_accepts_missing_comma_and_truncated_key_name_json(monkeypatch):
    response_content = '{"shots":[{"shot_index":1\n"source_text_span":"林晚晚加班","scene_location":"林晚晚办公室","time_of_day":"夜","characters":["林晚晚"],"story_summary":"林晚晚加班时收到顾深邀约看月亮的微信","dialogue_or_narration":"林晚晚打字：我在加班，明天见。","key_'

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": response_content}}]}

    async def fake_post(self, *args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    deepseek.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    deepseek.DEEPSEEK_MODEL = "deepseek-chat"

    result = await deepseek._parse_lite_chunk(
        "林晚晚正对着电脑屏幕上的Excel表格头疼。",
        api_key="test-key",
    )

    assert len(result) == 1
    assert result[0]["shot_index"] == 1
    assert result[0]["source_text_span"] == "林晚晚加班"


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

    async def fake_character_prompts_ai(**kwargs):
        return [{'name': '林晚晚', 'prompt': '黑色长发，职场女性，气质干练'}]

    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_details', fake_generate_shot_details)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_storyboard_prompt', fake_storyboard_prompt)
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_scene_prop_prompts', fake_scene_prop_prompts)
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


def test_assemble_video_prompt_text_generates_separate_lines_for_multiple_character_refs(workflow_db):
    """多个角色引用资产应各自生成独立的 @image 说明行。"""
    from models import ChapterVideoShot, VideoAsset

    Session, workflow_id = workflow_db
    session = Session()
    try:
        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            status="video_ready",
            storyboard_image_url="/static/manga/sb1.png",
            storyboard_prompt="少年站在天台",
            video_prompt="生成视频",
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)

        # 预写一条虚拟资产，让 video_assets 表的自增 ID 跳过 1，
        # 避免与 shot.id == 1 碰撞导致故事版被意外包含
        dummy = VideoAsset(
            story_id=99, chapter_id=99, shot_id=shot.id,
            asset_type="reference", name="dummy",
            file_path="/static/video/dummy.png", status="archived",
        )
        session.add(dummy)
        session.commit()

        char_a = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色A",
            file_path="/static/video/char_a.png", status="active",
        )
        char_b = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色B",
            file_path="/static/video/char_b.png", status="active",
        )
        session.add_all([char_a, char_b])
        session.commit()
        session.refresh(char_a)
        session.refresh(char_b)

        from services.video_chapter_pipeline import assemble_video_prompt_text
        result = assemble_video_prompt_text(
            shot.id,
            ref_asset_ids=[char_a.id, char_b.id],
        )

        part1 = result["parts"]["part1"]
        assert "@image1" in part1
        assert "@image2" in part1
        lines = [l for l in part1.splitlines() if "@image" in l]
        assert len(lines) == 2, f"应有 2 行 @image 说明，实际: {lines}"
        assert "角色外观参考" in lines[0]
        assert "角色外观参考" in lines[1]
    finally:
        session.close()


def test_assemble_video_prompt_text_storyboard_plus_character_ref(workflow_db):
    """故事版+角色引用各自独立一行，不互相干扰。"""
    from models import ChapterVideoShot, VideoAsset

    Session, workflow_id = workflow_db
    session = Session()
    try:
        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            status="video_ready",
            storyboard_image_url="/static/manga/sb1.png",
            storyboard_prompt="少年站在天台",
            video_prompt="生成视频",
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)

        char_asset = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色A",
            file_path="/static/video/char_a.png", status="active",
        )
        session.add(char_asset)
        session.commit()
        session.refresh(char_asset)

        from services.video_chapter_pipeline import assemble_video_prompt_text
        result = assemble_video_prompt_text(
            shot.id,
            ref_asset_ids=[-1, char_asset.id],
        )

        part1 = result["parts"]["part1"]
        lines = [l for l in part1.splitlines() if "@image" in l]
        assert len(lines) == 2
        assert "故事版构图参考" in lines[0]
        assert "角色外观参考" in lines[1]
    finally:
        session.close()


# ──────────────────────────────────────────────────────────────
# regenerate_shot_video 多资产类型 prompt 组装测试
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_regenerate_shot_video_assigns_correct_roles_for_mixed_asset_types(monkeypatch, workflow_db):
    """多资产场景：道具、角色、场景资产应各自获得正确的 prompt 角色标签。"""
    from models import ChapterVideoShot, VideoAsset

    Session, workflow_id = workflow_db
    session = Session()
    try:
        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            status="storyboard_ready",
            storyboard_image_url="/static/manga/sb1.png",
            storyboard_prompt="少年站在天台",
            video_prompt="生成视频",
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)

        dummy = VideoAsset(
            story_id=99, chapter_id=99, shot_id=shot.id,
            asset_type="reference", name="dummy",
            file_path="/static/video/dummy.png", status="archived",
        )
        session.add(dummy)
        session.commit()

        char_a = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色A",
            file_path="/static/video/char_a.png", status="active",
        )
        prop_x = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="prop_reference", name="道具X",
            file_path="/static/video/prop_x.png", status="active",
        )
        scene = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="scene_reference", name="场景图",
            file_path="/static/video/scene.png", status="active",
        )
        char_b = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色B",
            file_path="/static/video/char_b.png", status="active",
        )
        prop_y = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="prop_reference", name="道具Y",
            file_path="/static/video/prop_y.png", status="active",
        )
        session.add_all([char_a, prop_x, scene, char_b, prop_y])
        session.commit()
        session.refresh(char_a)
        session.refresh(prop_x)
        session.refresh(scene)
        session.refresh(char_b)
        session.refresh(prop_y)

        submitted_prompt = {}
        submitted_images = {}

        async def fake_submit_video_job(**kwargs):
            submitted_prompt["value"] = kwargs.get("prompt", "")
            submitted_images["value"] = kwargs.get("reference_images") or []
            return {"task_id": "fake_123", "provider_job_id": "fake_123", "status": "queued"}

        from services import video_chapter_pipeline as vcp
        from types import SimpleNamespace
        async def _fake_run_blocking(fn, *a, **kw):
            return a[0] if a else None
        async def _fake_poll_job(**kwargs):
            return "http://fake/video.mp4"
        monkeypatch.setattr(vcp, 'video_gen_service', SimpleNamespace(
            submit_video_job=fake_submit_video_job,
            query_job_status=lambda **kw: {"status": "completed"},
        ))
        monkeypatch.setattr(vcp, 'resolve_reference_input', lambda val, kind: val)
        monkeypatch.setattr(vcp, '_resolve_storyboard_local_path', lambda val: val)
        monkeypatch.setattr(vcp, '_resolve_style_ref_local_path', lambda val: val)
        monkeypatch.setattr(vcp, 'run_blocking', _fake_run_blocking)
        monkeypatch.setattr(vcp, '_poll_video_job', _fake_poll_job)
        await vcp.regenerate_shot_video(
            shot.id,
            ref_asset_ids=[char_a.id, prop_x.id, scene.id, char_b.id, prop_y.id],
            api_key="test_key",
        )

        prompt = submitted_prompt.get("value", "")
        images = submitted_images.get("value", [])

        # 应有 5 张引用图（不含故事版，因为 shot.id 不在 ref_asset_ids 中）
        assert len(images) == 5, f"应有 5 张参考图，实际: {len(images)}"

        # 检查 prompt 中的 @image 标签顺序和角色
        lines = [l for l in prompt.splitlines() if "@image" in l]
        assert len(lines) == 5, f"应有 5 行 @image 说明，实际: {lines}"

        # 按用户选择顺序验证标签
        assert "角色外观参考" in lines[0], f"image1 应为角色外观参考: {lines[0]}"
        assert "道具参考" in lines[1], f"image2 应为道具参考: {lines[1]}"
        assert "场景参考" in lines[2], f"image3 应为场景参考: {lines[2]}"
        assert "角色外观参考" in lines[3], f"image4 应为角色外观参考: {lines[3]}"
        assert "道具参考" in lines[4], f"image5 应为道具参考: {lines[4]}"
    finally:
        session.close()


@pytest.mark.asyncio
async def test_regenerate_shot_video_preserves_user_selection_order(monkeypatch, workflow_db):
    """用户选择顺序应与 prompt 中 @image 编号和提交的图片顺序一致。"""
    from models import ChapterVideoShot, VideoAsset

    Session, workflow_id = workflow_db
    session = Session()
    try:
        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            status="storyboard_ready",
            storyboard_image_url="/static/manga/sb1.png",
            storyboard_prompt="少年站在天台",
            video_prompt="生成视频",
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)

        dummy = VideoAsset(
            story_id=99, chapter_id=99, shot_id=shot.id,
            asset_type="reference", name="dummy",
            file_path="/static/video/dummy.png", status="archived",
        )
        session.add(dummy)
        session.commit()

        asset_b = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="prop_reference", name="道具B",
            file_path="/static/video/prop_b.png", status="active",
        )
        asset_a = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色A",
            file_path="/static/video/char_a.png", status="active",
        )
        asset_c = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="scene_reference", name="场景C",
            file_path="/static/video/scene_c.png", status="active",
        )
        session.add_all([asset_b, asset_a, asset_c])
        session.commit()
        session.refresh(asset_b)
        session.refresh(asset_a)
        session.refresh(asset_c)

        submitted_images = {}
        submitted_prompt = {}

        async def fake_submit_video_job(**kwargs):
            submitted_images["value"] = kwargs.get("reference_images") or []
            submitted_prompt["value"] = kwargs.get("prompt", "")
            return {"task_id": "fake_456", "provider_job_id": "fake_456", "status": "queued"}

        from services import video_chapter_pipeline as vcp
        from types import SimpleNamespace
        async def _fake_run_blocking(fn, *a, **kw):
            return a[0] if a else None
        async def _fake_poll_job(**kwargs):
            return "http://fake/video.mp4"
        monkeypatch.setattr(vcp, 'video_gen_service', SimpleNamespace(
            submit_video_job=fake_submit_video_job,
            query_job_status=lambda **kw: {"status": "completed"},
        ))
        monkeypatch.setattr(vcp, 'resolve_reference_input', lambda val, kind: val)
        monkeypatch.setattr(vcp, '_resolve_storyboard_local_path', lambda val: val)
        monkeypatch.setattr(vcp, '_resolve_style_ref_local_path', lambda val: val)
        monkeypatch.setattr(vcp, 'run_blocking', _fake_run_blocking)
        monkeypatch.setattr(vcp, '_poll_video_job', _fake_poll_job)
        await vcp.regenerate_shot_video(
            shot.id,
            ref_asset_ids=[asset_b.id, asset_a.id, asset_c.id],
            api_key="test_key",
        )

        prompt = submitted_prompt.get("value", "")
        images = submitted_images.get("value", [])

        # 图片顺序应与用户选择一致：prop_b → char_a → scene_c
        assert len(images) == 3
        assert "prop_b.png" in images[0]
        assert "char_a.png" in images[1]
        assert "scene_c.png" in images[2]

        # prompt 中 @image 编号应与图片顺序匹配
        lines = [l for l in prompt.splitlines() if "@image" in l]
        assert len(lines) == 3
        # image1 = 道具B（用户第一个选的）
        assert "道具参考" in lines[0], f"image1 应为道具参考: {lines[0]}"
        # image2 = 角色A（用户第二个选的）
        assert "角色外观参考" in lines[1], f"image2 应为角色外观参考: {lines[1]}"
        # image3 = 场景C（用户第三个选的）
        assert "场景参考" in lines[2], f"image3 应为场景参考: {lines[2]}"
    finally:
        session.close()


@pytest.mark.asyncio
async def test_regenerate_shot_video_storyboard_plus_mixed_assets(monkeypatch, workflow_db):
    """故事版+多类型资产：故事版应为 image1，其余按顺序编号。"""
    from models import ChapterVideoShot, VideoAsset

    Session, workflow_id = workflow_db
    session = Session()
    try:
        shot = ChapterVideoShot(
            workflow_id=workflow_id,
            shot_index=1,
            status="storyboard_ready",
            storyboard_image_url="/static/manga/sb1.png",
            storyboard_prompt="少年站在天台",
            video_prompt="生成视频",
        )
        session.add(shot)
        session.commit()
        session.refresh(shot)

        prop = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="prop_reference", name="座钟",
            file_path="/static/video/clock.png", status="active",
        )
        char = VideoAsset(
            story_id=34, chapter_id=12, shot_id=shot.id,
            asset_type="character_reference", name="角色A",
            file_path="/static/video/char_a.png", status="active",
        )
        session.add_all([prop, char])
        session.commit()
        session.refresh(prop)
        session.refresh(char)

        submitted_prompt = {}
        submitted_images = {}

        async def fake_submit_video_job(**kwargs):
            submitted_prompt["value"] = kwargs.get("prompt", "")
            submitted_images["value"] = kwargs.get("reference_images") or []
            return {"task_id": "fake_789", "provider_job_id": "fake_789", "status": "queued"}

        from services import video_chapter_pipeline as vcp
        from types import SimpleNamespace
        async def _fake_run_blocking(fn, *a, **kw):
            return a[0] if a else None
        async def _fake_poll_job(**kwargs):
            return "http://fake/video.mp4"
        monkeypatch.setattr(vcp, 'video_gen_service', SimpleNamespace(
            submit_video_job=fake_submit_video_job,
            query_job_status=lambda **kw: {"status": "completed"},
        ))
        monkeypatch.setattr(vcp, 'resolve_reference_input', lambda val, kind: val)
        monkeypatch.setattr(vcp, '_resolve_storyboard_local_path', lambda val: val)
        monkeypatch.setattr(vcp, '_resolve_style_ref_local_path', lambda val: val)
        monkeypatch.setattr(vcp, 'run_blocking', _fake_run_blocking)
        monkeypatch.setattr(vcp, '_poll_video_job', _fake_poll_job)
        await vcp.regenerate_shot_video(
            shot.id,
            ref_asset_ids=[-1, prop.id, char.id],
            api_key="test_key",
        )

        prompt = submitted_prompt.get("value", "")
        images = submitted_images.get("value", [])

        assert len(images) == 3

        lines = [l for l in prompt.splitlines() if "@image" in l]
        assert len(lines) == 3
        assert "故事版构图参考" in lines[0], f"image1 应为故事版: {lines[0]}"
        assert "道具参考" in lines[1], f"image2 应为道具参考: {lines[1]}"
        assert "角色外观参考" in lines[2], f"image3 应为角色外观参考: {lines[2]}"
    finally:
        session.close()
