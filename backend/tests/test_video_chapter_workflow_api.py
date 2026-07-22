import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sqlalchemy.exc import InvalidRequestError

from routers import video as video_router
from schemas import ChapterVideoWorkflowCreate
from services import oss as oss_service
from services import video_chapter_pipeline

# 符合 is_valid_storyboard_prompt 校验的测试用提示词
_VALID_STORYBOARD_PROMPT = """# 电影故事板生成提示词

## 项目总设定栏（顶部窄栏）

【镜头】测试镜头 | 【类型】情感短剧 | 【时长】15秒 | 【风格】日式动漫风
【地点】旧宅走廊·夜 | 【情绪】迟疑转为警觉 | 【叙事】递进

### 角色设定区

角色：林秋 | 动作：站在走廊中央，正对镜头 | 表情：警觉

## 场景与环境设定区

场景：旧宅走廊，月光从半掩窗户洒入，木质地板上投下窗棂阴影
空间布局：林秋站在画面中央偏左，右侧是通往二楼的楼梯

## 核心分镜故事板

### 段落1：0-4.2s
画面：林秋停在走廊中央，月光从半掩窗户洒入
景别：中景
镜头运动：缓慢推近
情绪：迟疑

### 段落2：4.2-9.5s
画面：林秋缓缓转头看向楼梯方向
景别：中近景
镜头运动：跟随视线平摇

## 灯光/镜头/剪辑/声音设计区

灯光：月光为主光源（冷白），辅以走廊顶灯（暖黄）
焦距：50mm
节奏：慢速递进"""


class _FakeDb:
    def __init__(self):
        self.refresh_calls: list[object] = []

    def refresh(self, obj: object):
        self.refresh_calls.append(obj)
        raise InvalidRequestError("Instance is not persistent within this Session")

    def get(self, model, pk):
        if getattr(model, "__name__", "") == "Story":
            return SimpleNamespace(id=pk, owner_user_id=1)
        return None


def test_api_create_chapter_workflow_does_not_refresh_detached_instance(monkeypatch):
    db = _FakeDb()
    init_db_calls: list[dict[str, object]] = []
    ownership_checks: list[tuple[list[int], int, object]] = []
    detached_workflow = SimpleNamespace(
        id=77,
        chapter_id=440,
        story_id=900,
        workflow_status="pending",
        character_reference_ids=[11, 22],
        video_style="写实电影感",
        duration_per_shot=10,
        total_shots=0,
        completed_shots=0,
        failed_shots=0,
        error_message=None,
        created_at=None,
        updated_at=None,
        shots=[],
    )
    persistent_workflow = SimpleNamespace(
        id=77,
        chapter_id=440,
        story_id=900,
        workflow_status="pending",
        character_reference_ids=[11, 22],
        video_style="写实电影感",
        duration_per_shot=10,
        total_shots=0,
        completed_shots=0,
        failed_shots=0,
        error_message=None,
        created_at=None,
        updated_at=None,
        shots=[],
    )

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router,
        "_require_chapter_for_user",
        lambda chapter_id, user, db_session: SimpleNamespace(id=chapter_id, story_id=900, novel_content="章节正文"),
    )
    monkeypatch.setattr(video_router, "create_chapter_workflow", lambda **kwargs: detached_workflow)
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: persistent_workflow)
    monkeypatch.setattr(
        video_router,
        "_require_reference_assets_for_story",
        lambda asset_ids, story_id, db_session: ownership_checks.append((asset_ids, story_id, db_session)),
    )
    monkeypatch.setattr(video_router, "init_db", lambda **kwargs: init_db_calls.append(kwargs), raising=False)

    result = asyncio.run(
        video_router.api_create_chapter_workflow(
            body=ChapterVideoWorkflowCreate(chapter_id=440, character_reference_ids=[11, 22], video_style="写实电影感"),
            request=SimpleNamespace(),
            db=db,
        )
    )

    assert result is persistent_workflow
    assert ownership_checks == [([11, 22], 900, db)]
    assert db.refresh_calls == []
    assert init_db_calls == []


def test_workflow_status_reconciles_failed_background_parse(monkeypatch):
    """后台拆镜已失败时，状态接口不得继续返回 parsing_shots。"""
    persisted_workflow = SimpleNamespace(
        id=11,
        chapter_id=444,
        story_id=900,
        workflow_status="parsing_shots",
        total_shots=0,
        completed_shots=0,
        failed_shots=0,
        error_message=None,
    )
    failed_task = SimpleNamespace(
        task_id="chapter_video_11_stage_deadbeef",
        status="failed",
        retry_count=1,
        max_retries=1,
        error_message="上游拆镜服务失败",
        metadata_json={"stage": "failed", "message": "上游拆镜服务失败"},
    )

    class _StatusDb:
        def __init__(self):
            self.commit_called = False

        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "Story":
                return SimpleNamespace(id=pk, owner_user_id=1)
            if name == "ChapterVideoWorkflow":
                return persisted_workflow
            return None

        def commit(self):
            self.commit_called = True

    db = _StatusDb()
    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: persisted_workflow)
    monkeypatch.setattr(video_router, "_latest_chapter_workflow_task", lambda db_session, workflow_id: failed_task)

    result = asyncio.run(
        video_router.api_get_chapter_workflow_status(
            workflow_id=11,
            request=SimpleNamespace(),
            db=db,
        )
    )

    assert result.workflow_status == "failed"
    assert result.error_message == "上游拆镜服务失败"
    assert persisted_workflow.workflow_status == "failed"
    assert persisted_workflow.error_message == "上游拆镜服务失败"
    assert db.commit_called


def test_regenerate_shot_storyboard_uses_workflow_lookup_for_chapter_id(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt=_VALID_STORYBOARD_PROMPT,
            character_reference_ids=[],
        ),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'get_workflow', lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440))
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key'))

    assert captured['chapter_id'] == 440
    assert result is not None


def test_regenerate_shot_storyboard_uses_reference_images_and_labels(monkeypatch):
    captured: dict[str, object] = {}
    persisted: dict[str, object] = {}
    resolver_calls: list[tuple[int, list[int], str]] = []

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt=_VALID_STORYBOARD_PROMPT,
            character_reference_ids=[31],
            scene_reference_ids=[32],
            prop_reference_ids=[33],
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440, story_id=901),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)

    def fake_resolve(story_id, ref_ids, context_text):
        resolver_calls.append((story_id, ref_ids, context_text))
        return [(Path('C:/tmp/ref-12.png'), '林秋', 'character')]

    monkeypatch.setattr(video_chapter_pipeline, '_resolve_video_asset_references', fake_resolve)
    monkeypatch.setattr(video_chapter_pipeline, '_persist_chapter_storyboard_asset', lambda **kwargs: persisted.update(kwargs))

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key', ref_asset_ids=[12]))

    assert captured['ref_image_paths'] == ['C:/tmp/ref-12.png']
    assert captured['ref_labels'] == ['林秋']
    assert captured['ref_roles'] == ['character']
    assert captured['suppress_default_style'] is True
    assert 'style_ref_path' not in captured
    assert len(resolver_calls) == 1
    assert resolver_calls[0][0:2] == (901, [12])
    assert resolver_calls[0][2]
    assert persisted['source_asset_ids'] == [12]
    assert result is not None


def test_regenerate_shot_storyboard_merges_default_reference_asset_ids(monkeypatch):
    """未显式传引用时，按角色、场景、道具顺序合并并去重。"""
    captured: dict[str, object] = {}
    persisted: dict[str, object] = {}
    resolved_ids: list[int] = []

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt=_VALID_STORYBOARD_PROMPT,
            character_reference_ids=[12, 13],
            scene_reference_ids=[13, 14],
            prop_reference_ids=[None, 15, "invalid", 12],
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440, story_id=901),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)

    def fake_resolve(story_id, ref_ids, context_text):
        assert story_id == 901
        assert context_text
        resolved_ids.extend(ref_ids)
        return [
            (Path('C:/tmp/character.png'), '林秋', 'character'),
            (Path('C:/tmp/character-2.png'), '周宁', 'character'),
            (Path('C:/tmp/scene.png'), '旧宅走廊', 'scene'),
            (Path('C:/tmp/prop.png'), '木簪', 'prop'),
        ]

    monkeypatch.setattr(video_chapter_pipeline, '_resolve_video_asset_references', fake_resolve)
    monkeypatch.setattr(video_chapter_pipeline, '_persist_chapter_storyboard_asset', lambda **kwargs: persisted.update(kwargs))

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key'))

    assert resolved_ids == [12, 13, 14, 15]
    assert captured['ref_image_paths'] == [
        'C:/tmp/character.png',
        'C:/tmp/character-2.png',
        'C:/tmp/scene.png',
        'C:/tmp/prop.png',
    ]
    assert captured['ref_labels'] == ['林秋', '周宁', '旧宅走廊', '木簪']
    assert captured['ref_roles'] == ['character', 'character', 'scene', 'prop']
    assert captured['suppress_default_style'] is True
    assert 'style_ref_path' not in captured
    assert persisted['source_asset_ids'] == [12, 13, 14, 15]
    assert result is not None


def test_regenerate_shot_storyboard_does_not_inject_style_preset(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt=_VALID_STORYBOARD_PROMPT,
            character_reference_ids=[],
            scene_reference_ids=[],
            prop_reference_ids=[],
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(
            id=workflow_id,
            chapter_id=440,
            story_id=901,
            video_style='日式动漫风',
            style_reference_image_url='C:/tmp/style.png',
        ),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_video_asset_references', lambda *_args: [])
    monkeypatch.setattr(video_chapter_pipeline, '_persist_chapter_storyboard_asset', lambda **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_pick_style_anchor_image',
        lambda *_args: (_ for _ in ()).throw(AssertionError('不应读取风格锚点')),
    )

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key'))

    assert captured['ref_image_paths'] is None
    assert captured['ref_labels'] is None
    assert captured['ref_roles'] is None
    assert 'style_ref_path' not in captured
    assert captured['suppress_default_style'] is True
    assert result is not None


def test_storyboard_director_messages_ignore_style_preset():
    from services.video_chapter_prompts import build_storyboard_director_messages

    system_prompt, user_prompt = build_storyboard_director_messages(
        scene_location="旧宅走廊",
        time_of_day="夜",
        characters=["林秋"],
        story_summary="林秋停在走廊中央",
        dialogue_or_narration="她没有继续向前。",
        camera_plan="中景缓慢推近",
        motion_plan="停步，抬眼",
        emotion_plan="迟疑转为警觉",
        style_preset="日式动漫风",
    )

    combined = f"{system_prompt}\n{user_prompt}"
    assert "日式动漫风" not in combined
    assert "style_preset" not in combined
    assert "风格预设约束" not in combined


def test_regenerate_shot_storyboard_logs_reference_inputs(monkeypatch, caplog):
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt=_VALID_STORYBOARD_PROMPT,
            character_reference_ids=[12],
            scene_reference_ids=[],
            prop_reference_ids=[],
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440, story_id=901),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_resolve_video_asset_references',
        lambda story_id, ref_ids, context_text: [
            ('https://user:password@cdn.example.com/ref-12.png?signature=SECRET&token=SECRET#fragment', '林秋', 'character'),
            (Path('C:/tmp/ref-13.png'), '旧宅走廊', 'scene'),
        ],
    )
    monkeypatch.setattr(video_chapter_pipeline, '_persist_chapter_storyboard_asset', lambda **kwargs: None)

    async def fake_generate_manga_image(**kwargs):
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key', ref_asset_ids=[12]))

    assert '故事版参考图 1 [local]: https://cdn.example.com/ref-12.png' in caplog.text
    assert '故事版参考图 2 [local]: C:/tmp/ref-13.png' in caplog.text
    assert 'SECRET' not in caplog.text
    assert 'user:password' not in caplog.text


def test_regenerate_shot_storyboard_localizes_remote_refs_before_generation(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt=_VALID_STORYBOARD_PROMPT,
            character_reference_ids=[12],
            scene_reference_ids=[],
            prop_reference_ids=[],
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440, story_id=901),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_resolve_video_asset_references',
        lambda story_id, ref_ids, context_text: [(Path('C:/tmp/ref-12.png'), '林秋', 'character')],
    )
    monkeypatch.setattr(video_chapter_pipeline, '_persist_chapter_storyboard_asset', lambda **kwargs: None)

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key', ref_asset_ids=[12]))

    assert captured['ref_image_paths'] == ['C:/tmp/ref-12.png']
    assert captured['ref_labels'] == ['林秋']
    assert captured['ref_roles'] == ['character']
    assert captured['suppress_default_style'] is True
    assert 'style_ref_path' not in captured
    assert result is not None


def test_resolve_ref_image_paths_accepts_http_urls(monkeypatch):
    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [SimpleNamespace(file_path='https://cdn.example.com/ref-86.png', status='active')]

    class _Db:
        def query(self, model):
            return _Query()

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value if kind == 'video' else None)

    result = video_chapter_pipeline._resolve_ref_image_paths(901, [86])

    assert result == ['https://cdn.example.com/ref-86.png']


def test_regenerate_shot_video_keeps_character_refs_separate_from_storyboard_refs(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            storyboard_image_url='https://cdn.example.com/storyboard-194.png',
            video_prompt='现成 video prompt',
            character_reference_ids=[86, 194],
            scene_location='办公室',
            time_of_day='深夜',
            characters=['林晚晚'],
            story_summary='林晚晚看向手机',
            camera_plan='推近',
            motion_plan='抬手点屏幕',
            emotion_plan='失神',
            continuity_notes='保持角色一致',
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url=None),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_resolve_video_asset_inputs',
        lambda story_id, ref_ids: [('C:/tmp/character-86.png', '林晚晚', 'character')],
    )
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: None)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: None)
    monkeypatch.setattr(oss_service, 'auto_configure_from_db', lambda: None)
    monkeypatch.setattr(oss_service, 'upload_file', lambda path: path)
    async def fake_poll_video_job(**kwargs):
        return 'https://cdn.example.com/video.mp4'

    monkeypatch.setattr(video_chapter_pipeline, '_poll_video_job', fake_poll_video_job)

    class _ShotQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class _ChapterQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

        def first(self):
            return None

    class _Db:
        def query(self, model):
            name = getattr(model, '__name__', '')
            if name == 'ChapterVideoShot':
                return _ShotQuery()
            return _ChapterQuery()

        def get(self, model, pk):
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())

    async def fake_submit_video_job(**kwargs):
        captured.update(kwargs)
        return {'provider_job_id': 'job-1'}

    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, 'submit_video_job', fake_submit_video_job)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86, 194]))

    assert captured['reference_images'] == [
        'https://cdn.example.com/storyboard-194.png',
        'C:/tmp/character-86.png',
    ]
    assert result is not None


def test_regenerate_shot_video_logs_reference_roles(monkeypatch, caplog):
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            storyboard_image_url='https://cdn.example.com/storyboard-194.png',
            video_prompt='现成 video prompt',
            character_reference_ids=[86, -1],
            scene_location='办公室',
            time_of_day='深夜',
            characters=['林晚晚'],
            story_summary='林晚晚看向手机',
            camera_plan='推近',
            motion_plan='抬手点屏幕',
            emotion_plan='失神',
            continuity_notes='保持角色一致',
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url='https://cdn.example.com/style.png?signature=SECRET&token=SECRET#fragment'),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_resolve_video_asset_inputs',
        lambda story_id, ref_ids: [('C:/tmp/character-86.png', '林晚晚', 'character')],
    )
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: None)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: 'C:/tmp/style.png')
    monkeypatch.setattr(oss_service, 'auto_configure_from_db', lambda: None)
    monkeypatch.setattr(oss_service, 'upload_file', lambda path: path)
    async def fake_poll_video_job(**kwargs):
        return 'https://cdn.example.com/video.mp4'

    monkeypatch.setattr(video_chapter_pipeline, '_poll_video_job', fake_poll_video_job)

    class _Db:
        def query(self, model):
            class _Query:
                def filter(self, *args, **kwargs):
                    return self

                def first(self):
                    return None

                def all(self):
                    from types import SimpleNamespace
                    return [SimpleNamespace(id=86, asset_type='character_reference')]

            return _Query()

        def get(self, model, pk):
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())

    async def fake_submit_video_job(**kwargs):
        return {'provider_job_id': 'job-1'}

    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, 'submit_video_job', fake_submit_video_job)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86, -1]))

    assert '[video_submit]   参考图 1 [storyboard][remote]: https://cdn.example.com/storyboard-194.png' in caplog.text
    assert '[video_submit]   参考图 2 [character][local]: C:/tmp/character-86.png' in caplog.text
    assert '[video_submit]   参考图 3 [style][remote]: https://cdn.example.com/style.png' in caplog.text
    assert 'SECRET' not in caplog.text
    assert 'user:password' not in caplog.text


def test_regenerate_shot_video_preserves_storyboard_character_style_reference_order(monkeypatch):
    captured: dict[str, object] = {}
    uploaded_paths: list[str] = []

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            storyboard_image_url='https://cdn.example.com/storyboard-194.png',
            video_prompt='现成 video prompt',
            character_reference_ids=[86, 194],
            scene_location='办公室',
            time_of_day='深夜',
            characters=['林晚晚'],
            story_summary='林晚晚看向手机',
            camera_plan='推近',
            motion_plan='抬手点屏幕',
            emotion_plan='失神',
            continuity_notes='保持角色一致',
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url='https://cdn.example.com/style.png'),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_chapter_pipeline,
        '_resolve_video_asset_inputs',
        lambda story_id, ref_ids: [('C:/tmp/character-86.png', '林晚晚', 'character')],
    )
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: 'C:/tmp/storyboard-194.png')
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: 'C:/tmp/style.png')
    monkeypatch.setattr(oss_service, 'auto_configure_from_db', lambda: None)
    monkeypatch.setattr(
        oss_service,
        'upload_file',
        lambda path: uploaded_paths.append(path) or f'https://oss.example.com/{Path(path).name}',
    )

    async def fake_poll_video_job(**kwargs):
        return 'https://cdn.example.com/video.mp4'

    monkeypatch.setattr(video_chapter_pipeline, '_poll_video_job', fake_poll_video_job)

    class _Db:
        def query(self, model):
            class _Query:
                def filter(self, *args, **kwargs):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return _Query()

        def get(self, model, pk):
            if getattr(model, '__name__', '') == 'Chapter':
                return SimpleNamespace(video_style_preset_id=8)
            if getattr(model, '__name__', '') == 'VideoStylePreset':
                return SimpleNamespace(prompt_template='文字冲突画风')
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())

    async def fake_submit_video_job(**kwargs):
        captured.update(kwargs)
        return {'provider_job_id': 'job-1'}

    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, 'submit_video_job', fake_submit_video_job)

    asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86, 194]))

    assert captured['reference_images'] == [
        'https://cdn.example.com/storyboard-194.png',
        'https://oss.example.com/character-86.png',
        'https://cdn.example.com/style.png',
    ]
    assert uploaded_paths == ['C:/tmp/character-86.png']
    assert '文字冲突画风' not in captured['prompt']
    assert 'Visual style:' not in captured['prompt']


def test_resolve_workflow_style_ref_path_accepts_oss_url(monkeypatch):
    monkeypatch.setattr(
        video_router,
        'ChapterVideoWorkflow',
        SimpleNamespace(chapter_id='chapter_id', created_at=SimpleNamespace(desc=lambda: 'created_at_desc')),
    )
    monkeypatch.setattr(video_router, 'Chapter', SimpleNamespace(id='id'))

    class _WorkflowQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(style_reference_image_url='https://cdn.example.com/style.png')

    class _Db:
        def query(self, model):
            return _WorkflowQuery()

    monkeypatch.setattr(
        video_router,
        'ensure_local_media_path',
        lambda value, kind: 'C:/tmp/style.png' if value == 'https://cdn.example.com/style.png' and kind == 'manga' else None,
    )

    result = video_router._resolve_workflow_style_ref_path(440, _Db())

    assert result == 'C:/tmp/style.png'


@pytest.mark.parametrize(
    'source_url',
    [
        'https://cdn.example.com/style.png?signature=abc',
        'http://images.example.com/style.png',
    ],
)
def test_video_style_reference_input_reuses_public_url(monkeypatch, source_url):
    def fail_localize(_value):
        raise AssertionError('公开 URL 不应下载为本地文件后再次上传 OSS')

    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', fail_localize)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)

    assert video_chapter_pipeline._resolve_style_reference_input(source_url) == source_url


def test_video_style_reference_input_resolves_preset_relative_path(monkeypatch):
    captured: list[str] = []

    def resolve_local(value):
        captured.append(value)
        return 'C:/app/backend/manga_outputs/style-presets/preset.png'

    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', resolve_local)

    result = video_chapter_pipeline._resolve_style_reference_input('style-presets/preset.png')

    assert result == 'C:/app/backend/manga_outputs/style-presets/preset.png'
    assert captured == ['style-presets/preset.png']


def test_from_video_url_keeps_https_url():
    assert video_router._from_video_url('https://cdn.example.com/video.mp4') == 'https://cdn.example.com/video.mp4'


def test_to_storyboard_static_url_keeps_https_url():
    assert video_chapter_pipeline._to_storyboard_static_url('https://cdn.example.com/storyboard.png') == 'https://cdn.example.com/storyboard.png'


def test_normalize_chapter_shot_uses_15_seconds_default():
    result = video_router._normalize_chapter_shot({}, 1, 15)

    assert result["duration_seconds"] == 15


def test_fallback_chapter_storyboard_uses_15_seconds():
    shots = video_router._fallback_chapter_storyboard("她停下脚步。\n她抬头。", 2)

    assert shots
    assert all(shot["duration_seconds"] == 15 for shot in shots)


def test_storyboard_director_prompt_no_longer_uses_10s_beats():
    from services import video_chapter_prompts as prompts

    assert "0-3 秒" not in prompts.STORYBOARD_DIRECTOR_SYSTEM_PROMPT
    assert "3-7 秒" not in prompts.STORYBOARD_DIRECTOR_SYSTEM_PROMPT
    assert "7-10 秒" not in prompts.STORYBOARD_DIRECTOR_SYSTEM_PROMPT


def test_shot_detail_prompt_no_longer_uses_10s_storyboard_beats():
    from services import video_chapter_prompts as prompts

    assert "0-3 秒" not in prompts.SHOT_DETAIL_USER_PROMPT_TEMPLATE
    assert "3-7 秒" not in prompts.SHOT_DETAIL_USER_PROMPT_TEMPLATE
    assert "7-10 秒" not in prompts.SHOT_DETAIL_USER_PROMPT_TEMPLATE
    assert "15 秒镜头" in prompts.SHOT_DETAIL_USER_PROMPT_TEMPLATE


def test_regenerate_shot_video_submits_15_second_duration(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            storyboard_image_url='https://cdn.example.com/storyboard-194.png',
            video_prompt='现成 video prompt',
            character_reference_ids=[86],
            scene_location='办公室',
            time_of_day='深夜',
            characters=['林晚晚'],
            story_summary='林晚晚看向手机',
            camera_plan='推近',
            motion_plan='抬手点屏幕',
            emotion_plan='失神',
            continuity_notes='保持角色一致',
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url=None),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_ref_image_paths', lambda story_id, ref_ids: ['https://cdn.example.com/character-86.png'])
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: None)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: None)
    async def fake_poll_video_job(**kwargs):
        return 'https://cdn.example.com/video.mp4'

    monkeypatch.setattr(video_chapter_pipeline, '_poll_video_job', fake_poll_video_job)

    class _Db:
        def query(self, model):
            class _Query:
                def filter(self, *args, **kwargs):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return _Query()

        def get(self, model, pk):
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())

    async def fake_submit_video_job(**kwargs):
        captured.update(kwargs)
        return {'provider_job_id': 'job-1'}

    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, 'submit_video_job', fake_submit_video_job)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86]))

    assert captured['duration_seconds'] == 15
    assert result is not None


def test_regenerate_shot_video_submits_requested_duration_and_adapter(monkeypatch):
    captured = {}

    async def fake_submit(**kwargs):
        captured.update(kwargs)
        return {"provider_job_id": "job-1"}

    async def fake_poll(**kwargs):
        captured["poll_adapter_type"] = kwargs.get("adapter_type")
        return "/static/video/result.mp4"

    monkeypatch.setattr(video_chapter_pipeline, "get_shot", lambda shot_id: SimpleNamespace(
        id=shot_id, workflow_id=1, video_prompt="测试", character_reference_ids=[],
        storyboard_image_url="https://cdn.example.com/storyboard.png", characters=[], shot_index=1,
    ))
    monkeypatch.setattr(video_chapter_pipeline, "get_workflow", lambda workflow_id: None)
    updates = []
    monkeypatch.setattr(video_chapter_pipeline, "update_shot", lambda *args, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(video_chapter_pipeline, "_resolve_video_asset_inputs", lambda *args: [])
    monkeypatch.setattr(video_chapter_pipeline, "resolve_reference_input", lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, "submit_video_job", fake_submit)
    monkeypatch.setattr(video_chapter_pipeline, "_poll_video_job", fake_poll)

    asyncio.run(video_chapter_pipeline.regenerate_shot_video(
        194, api_key="video-key", ref_asset_ids=[-1], duration_seconds=9, adapter_type="openai_video"
    ))

    assert captured["duration_seconds"] == 9
    assert captured["adapter_type"] == "openai_video"
    assert captured["poll_adapter_type"] == "openai_video"
    assert "生成9秒视频" in captured["prompt"]
    assert "生成15秒视频" not in captured["prompt"]
    assert updates[0]["duration_seconds"] == 9


def test_regenerate_shot_video_rebuilds_legacy_10s_prompt(monkeypatch):
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            storyboard_image_url='https://cdn.example.com/storyboard-194.png',
            video_prompt='0-3 秒：她回头。3-7 秒：她停顿。7-10 秒：她离开。',
            character_reference_ids=[86],
            scene_location='办公室',
            time_of_day='深夜',
            characters=['林晚晚'],
            story_summary='林晚晚看向手机',
            camera_plan='推近',
            motion_plan='抬手点屏幕',
            emotion_plan='失神',
            continuity_notes='保持角色一致',
            storyboard_prompt='',
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url=None),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_ref_image_paths', lambda story_id, ref_ids: ['https://cdn.example.com/character-86.png'])
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: None)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: None)

    async def fake_poll_video_job(**kwargs):
        return 'https://cdn.example.com/video.mp4'

    async def fake_submit_video_job(**kwargs):
        return {'provider_job_id': 'job-1'}

    class _Db:
        def query(self, model):
            class _Query:
                def filter(self, *args, **kwargs):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return _Query()

        def get(self, model, pk):
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())
    monkeypatch.setattr(video_chapter_pipeline, '_poll_video_job', fake_poll_video_job)
    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, 'submit_video_job', fake_submit_video_job)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86]))

    assert result is not None


def test_poll_video_job_defaults_to_7200_seconds():
    assert video_chapter_pipeline._poll_video_job.__defaults__[3] == 7200


def test_poll_video_job_failed_status_raises_upstream_error(monkeypatch):
    from services.errors import UpstreamServiceError

    async def fake_query_job_status(**kwargs):
        return {"status": "failed", "error": "Lingdong video task failed"}

    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, "query_job_status", fake_query_job_status)

    with pytest.raises(UpstreamServiceError, match="Lingdong video task failed") as exc_info:
        asyncio.run(
            video_chapter_pipeline._poll_video_job(
                provider="sora",
                provider_job_id="job-failed",
                poll_interval=0,
            )
        )

    assert exc_info.value.retryable is False
    assert exc_info.value.provider == "sora"


def test_chapter_storyboard_prompt_mentions_15_second_shots():
    style_preset = 'cinematic'
    hint_line = 'Target approximately 12 shots.'
    ai_prompt = (
        "You are a professional film director. Read the chapter below and design a storyboard "
        "that tells the core story with cinematic impact.\n\n"
        "Guidelines:\n"
        "- Shot count: decide based on the story's dramatic needs. " + hint_line +
        "A typical chapter needs 8-25 well-crafted shots. Quality over quantity.\n"
        "- Duration: default 15s per shot.\n"
        "- Style: " + style_preset + ".\n"
    )

    assert 'default 15s per shot' in ai_prompt


def test_api_create_chapter_workflow_does_not_auto_start(monkeypatch):
    """创建工作流后不自动启动流水线——用户手动触发各阶段。"""
    db = _FakeDb()
    ownership_checks: list[tuple[list[int], int, object]] = []

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router,
        "_require_chapter_for_user",
        lambda chapter_id, user, db_session: SimpleNamespace(id=chapter_id, story_id=900, novel_content="章节正文"),
    )
    monkeypatch.setattr(video_router, "create_chapter_workflow", lambda **kw: SimpleNamespace(id=77))
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: SimpleNamespace(id=workflow_id))
    monkeypatch.setattr(
        video_router,
        "_require_reference_assets_for_story",
        lambda asset_ids, story_id, db_session: ownership_checks.append((asset_ids, story_id, db_session)),
    )
    monkeypatch.setattr(video_router, "init_db", lambda **kw: None, raising=False)

    result = asyncio.run(
        video_router.api_create_chapter_workflow(
            body=ChapterVideoWorkflowCreate(chapter_id=440, character_reference_ids=[11, 22], video_style="写实电影感"),
            request=SimpleNamespace(), db=db,
        )
    )

    assert result.id == 77
    assert ownership_checks == [([11, 22], 900, db)]


def test_api_parse_chapter_shots_refreshes_source_text_from_db(monkeypatch):
    """parse 端点应从 DB 读取最新章节内容，而非使用工作流创建时的快照。"""
    db_captured: dict[str, object] = {}

    class _ParseRefreshDb:
        def __init__(self):
            self.wf = SimpleNamespace(
                id=11, chapter_id=444, story_id=900,
                source_text="旧的快照内容",
                character_reference_ids=[],
            )
            self.commit_called = False

        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "Story":
                return SimpleNamespace(id=pk, owner_user_id=1)
            if name == "Chapter":
                return SimpleNamespace(id=pk, story_id=900, novel_content="新的章节正文")
            if name == "ChapterVideoWorkflow":
                return self.wf
            return None

        def commit(self):
            self.commit_called = True

    db = _ParseRefreshDb()

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router, "get_chapter_workflow",
        lambda workflow_id: SimpleNamespace(
            id=workflow_id, chapter_id=444, story_id=900,
            workflow_status="pending", source_text="旧的快照内容",
            character_reference_ids=[],
        ),
    )
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "fake-key")
    monkeypatch.setattr(
        video_router, "_get_story_character_reference_asset_ids",
        lambda story_id, db_session: [1001, 1002] if story_id == 900 else [],
    )

    async def fake_parse(**kwargs):
        db_captured["source_text"] = kwargs.get("source_text", "")
        return {"workflow_status": "shots_ready", "shot_count": 3}

    monkeypatch.setattr(video_router, "parse_chapter_shots", fake_parse)
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper", lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})
    monkeypatch.setattr(video_router, "update_chapter_workflow_status", lambda workflow_id, status: None)

    async def fake_submit_task(task_id=None, coro_func=None, **kwargs):
        db_captured["source_text"] = kwargs.get("source_text", "")
        db_captured["task_id"] = task_id
        return task_id

    monkeypatch.setattr(video_router.task_manager, "submit_task", fake_submit_task)

    result = asyncio.run(
        video_router.api_parse_chapter_shots(
            workflow_id=11, request=SimpleNamespace(), db=db,
        )
    )

    assert result["workflow_status"] == "parsing_shots"
    assert str(db_captured.get("task_id", "")).startswith("chapter_video_11_stage_")
    assert db_captured.get("source_text") == "新的章节正文", \
        f"应使用 DB 最新章节内容，而非旧快照，实际: {db_captured.get('source_text')}"
    assert db.wf.source_text == "新的章节正文", \
        "工作流 source_text 应从 DB 同步更新"
    assert db.wf.character_reference_ids == [1001, 1002], \
        "工作流 character_reference_ids 应从 DB 刷新（空列表→最新资产）"
    assert db.commit_called, "应提交更新"


def test_api_parse_chapter_shots_raises_400_on_empty_content(monkeypatch):
    """章节正文为空时返回 400 错误，而非发送空内容给 DeepSeek。"""
    from fastapi import HTTPException

    class _Db:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "Story":
                return SimpleNamespace(id=pk, owner_user_id=1)
            if name == "Chapter":
                return SimpleNamespace(id=pk, story_id=900, novel_content=None)
            return None

        def commit(self):
            pass

    db = _Db()

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router, "get_chapter_workflow",
        lambda workflow_id: SimpleNamespace(
            id=workflow_id, chapter_id=444, story_id=900,
            workflow_status="pending", source_text="",
            character_reference_ids=[],
        ),
    )
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper", lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "fake-key")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            video_router.api_parse_chapter_shots(
                workflow_id=11, request=SimpleNamespace(), db=db,
            )
        )

    assert exc_info.value.status_code == 400
    assert "章节正文为空" in exc_info.value.detail


def test_api_parse_chapter_shots_rejects_concurrent_parse(monkeypatch):
    from fastapi import HTTPException

    class _Db:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "Story":
                return SimpleNamespace(id=pk, owner_user_id=1)
            return None

        def commit(self):
            pass

    db = _Db()

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper", lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})
    monkeypatch.setattr(
        video_router, "get_chapter_workflow",
        lambda workflow_id: SimpleNamespace(
            id=workflow_id, chapter_id=444, story_id=900,
            workflow_status="parsing_shots", source_text="旧快照",
            character_reference_ids=[],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            video_router.api_parse_chapter_shots(
                workflow_id=11, request=SimpleNamespace(), db=db,
            )
        )

    assert exc_info.value.status_code == 400
    assert "正在拆镜中" in exc_info.value.detail


def test_build_shot_character_prompts_only_returns_prompts_for_profiled_characters():
    """角色不在 story.character_profiles 时由 AI fallback 生成，本函数不返回提示词。"""
    from services.video_chapter_pipeline import _build_chapter_shot_character_prompts

    shot = SimpleNamespace(characters=["林晚晚", "顾深"])
    story = SimpleNamespace(id=1, character_profiles="\n顾深：男主角，性格温柔。\n程砚：男二，冷酷总裁。")

    result = _build_chapter_shot_character_prompts(shot, story)

    names = {e["name"] for e in result}
    assert "林晚晚" not in names, "林晚晚不在 character_profiles 中，应留给 AI fallback"
    assert "顾深" in names, "顾深在 character_profiles 中，应获得提示词"
    gu_entry = next(e for e in result if e["name"] == "顾深")
    assert "参考角色档案" in gu_entry["prompt"], "顾深在 profiles 中，应包含角色档案引用"


def test_build_shot_character_prompts_skips_when_profiles_is_none():
    """story.character_profiles 为 None 时，所有角色留待 AI fallback。"""
    from services.video_chapter_pipeline import _build_chapter_shot_character_prompts

    shot = SimpleNamespace(characters=["林晚晚"])
    story = SimpleNamespace(id=1, character_profiles=None)

    result = _build_chapter_shot_character_prompts(shot, story)
    assert len(result) == 0, "character_profiles 为 None 时不应返回任何提示词"


def test_build_shot_character_prompts_empty_chars_returns_empty():
    from services.video_chapter_pipeline import _build_chapter_shot_character_prompts
    shot = SimpleNamespace(characters=[])
    story = SimpleNamespace(id=1, character_profiles="顾深：男主角")
    assert _build_chapter_shot_character_prompts(shot, story) == []


def test_storyboard_director_prompt_no_longer_uses_10s_segments():
    from services.video_chapter_prompts import build_storyboard_director_messages

    system_prompt, _ = build_storyboard_director_messages(
        scene_location="天台上",
        time_of_day="夜",
        characters=["少年"],
        story_summary="望月",
        dialogue_or_narration="无",
        camera_plan="推近",
        motion_plan="站定",
        emotion_plan="静谧",
        duration_seconds=15,
    )

    assert "0-1.5s" not in system_prompt
    assert "1.5-3s" not in system_prompt
    assert "8.5-10s" not in system_prompt
    assert "10秒" not in system_prompt
    assert "15秒" in system_prompt
    assert "分镜段落" in system_prompt


# ── _get_story_character_reference_asset_ids 增强（VideoAsset 兜底） ─────────────────


def test_get_story_character_reference_asset_ids_returns_version_refs():
    """正常路径：StoryCharacterVersion 有 ref_asset_id 时返回这些 ID。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models import Base, StoryCharacterVersion, VideoAsset

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        # 创建 2 个 VideoAsset 作为参考图
        a1 = VideoAsset(story_id=10, asset_type="story_character_reference", name="林晚晚", file_path="/fake/a1.png", status="active")
        a2 = VideoAsset(story_id=10, asset_type="story_character_reference", name="顾深", file_path="/fake/a2.png", status="active")
        session.add_all([a1, a2])
        session.flush()

        # 创建 2 个 StoryCharacterVersion 并设置 ref_asset_id
        v1 = StoryCharacterVersion(story_id=10, character_name="林晚晚", version_label="v1",
                                    appearance_card="黑色长发", is_default=True, ref_asset_id=a1.id)
        v2 = StoryCharacterVersion(story_id=10, character_name="顾深", version_label="v1",
                                    appearance_card="深蓝西装", is_default=True, ref_asset_id=a2.id)
        # 一个非默认版本，不应被返回
        v3 = StoryCharacterVersion(story_id=10, character_name="程砚", version_label="非默认",
                                    appearance_card="冷酷", is_default=False, ref_asset_id=None)
        session.add_all([v1, v2, v3])
        session.commit()

        result = video_router._get_story_character_reference_asset_ids(story_id=10, db=session)
        # 应只返回 a1.id 和 a2.id
        assert sorted(result) == sorted([a1.id, a2.id]), f"预期 [a1.id, a2.id]，实际 {result}"
    finally:
        session.close()


def test_get_story_character_reference_asset_ids_falls_back_to_video_asset():
    """兜底路径：StoryCharacterVersion 无 ref_asset_id 时，从 VideoAsset 表查找。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models import Base, StoryCharacterVersion, VideoAsset

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        # StoryCharacterVersion 存在但 ref_asset_id 为 None
        v = StoryCharacterVersion(story_id=10, character_name="林晚晚", version_label="v1",
                                   appearance_card="黑色长发", is_default=True, ref_asset_id=None)
        session.add(v)

        # VideoAsset 有该故事的角色参考图
        a1 = VideoAsset(story_id=10, asset_type="story_character_reference", name="林晚晚-角色卡",
                         file_path="/fake/a1.png", status="active")
        a2 = VideoAsset(story_id=10, asset_type="character_reference", name="林晚晚-镜头级",
                         file_path="/fake/a2.png", status="active")
        # 另一个故事的资产，不应被返回
        a3 = VideoAsset(story_id=99, asset_type="story_character_reference", name="其他故事",
                         file_path="/fake/a3.png", status="active")
        session.add_all([a1, a2, a3])
        session.commit()

        result = video_router._get_story_character_reference_asset_ids(story_id=10, db=session)
        assert a1.id in result, f"story_character_reference 资产应被找到，结果: {result}"
        assert a2.id in result, f"character_reference 资产应被找到，结果: {result}"
        assert a3.id not in result, f"其他故事的资产不应被返回，结果: {result}"
    finally:
        session.close()


def test_get_story_character_reference_asset_ids_returns_empty_when_nothing_found():
    """没有任何匹配时返回空列表。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models import Base, StoryCharacterVersion, VideoAsset

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        # 存在版本但 ref_asset_id=None，且没有对应的 VideoAsset
        v = StoryCharacterVersion(story_id=10, character_name="林晚晚", version_label="v1",
                                   appearance_card="黑色长发", is_default=True, ref_asset_id=None)
        session.add(v)

        # 另一个故事的 VideoAsset
        a = VideoAsset(story_id=99, asset_type="story_character_reference", name="其他",
                        file_path="/fake/a.png", status="active")
        session.add(a)
        session.commit()

        result = video_router._get_story_character_reference_asset_ids(story_id=10, db=session)
        assert result == [], f"应返回空列表，实际 {result}"
    finally:
        session.close()


def test_get_story_character_reference_asset_ids_prefers_version_refs_over_video_asset():
    """优先级：StoryCharacterVersion.ref_asset_id 优先于 VideoAsset 兜底。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models import Base, StoryCharacterVersion, VideoAsset

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        # VideoAsset 存在
        a = VideoAsset(story_id=10, asset_type="character_reference", name="林晚晚",
                        file_path="/fake/a.png", status="active")
        session.add(a)
        session.flush()

        # StoryCharacterVersion 有 ref_asset_id → 应优先返回
        v = StoryCharacterVersion(story_id=10, character_name="林晚晚", version_label="v1",
                                   appearance_card="黑色长发", is_default=True, ref_asset_id=a.id)
        session.add(v)

        # 额外的 VideoAsset 没有对应版本 → 版本有 ref_asset_id 时不应进入兜底路径
        a_extra = VideoAsset(story_id=10, asset_type="character_reference", name="顾深-额外",
                              file_path="/fake/extra.png", status="active")
        session.add(a_extra)
        session.commit()

        result = video_router._get_story_character_reference_asset_ids(story_id=10, db=session)
        # 只有 v.ref_asset_id（a.id），不包括 a_extra.id
        assert result == [a.id], f"应只返回版本引用的 asset_id，实际 {result}"
    finally:
        session.close()
