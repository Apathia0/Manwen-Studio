import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sqlalchemy.exc import InvalidRequestError

from routers import video as video_router
from schemas import ChapterVideoWorkflowCreate
from services import video_chapter_pipeline


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

    async def fake_start_background(workflow_id: int, api_key: str | None = None, **kwargs):
        return f"chapter_video_{workflow_id}"

    monkeypatch.setattr(video_router, "start_workflow_background", fake_start_background)
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: persistent_workflow)
    monkeypatch.setattr(video_router, "init_db", lambda **kwargs: init_db_calls.append(kwargs), raising=False)

    result = asyncio.run(
        video_router.api_create_chapter_workflow(
            body=ChapterVideoWorkflowCreate(chapter_id=440, character_reference_ids=[11, 22], video_style="写实电影感"),
            request=SimpleNamespace(),
            db=db,
        )
    )

    assert result is persistent_workflow
    assert db.refresh_calls == []
    assert init_db_calls == [{"run_migrations": True, "raise_errors": True}]


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
            storyboard_prompt='现成 prompt',
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
            storyboard_prompt='现成 prompt',
            character_reference_ids=[12],
        ),
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_workflow',
        lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440, story_id=901),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_ref_image_paths', lambda story_id, ref_ids: ['C:/tmp/ref-12.png'])
    monkeypatch.setattr(video_chapter_pipeline, '_pick_style_anchor_image', lambda workflow_id, shot_id: None)

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key', ref_asset_ids=[12]))

    assert captured['ref_image_paths'] == ['C:/tmp/ref-12.png']
    assert captured['ref_labels'] == ['林秋']
    assert result is not None


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
            storyboard_prompt='现成 prompt',
            character_reference_ids=[12],
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
        '_resolve_ref_image_paths',
        lambda story_id, ref_ids: ['C:/tmp/ref-12.png', 'C:/tmp/ref-13.png'],
    )
    monkeypatch.setattr(video_chapter_pipeline, '_pick_style_anchor_image', lambda workflow_id, shot_id: None)

    async def fake_generate_manga_image(**kwargs):
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    with caplog.at_level('INFO', logger=video_chapter_pipeline.logger.name):
        asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key', ref_asset_ids=[12]))

    assert '故事版参考图 1 [local]: C:/tmp/ref-12.png' in caplog.text
    assert '故事版参考图 2 [local]: C:/tmp/ref-13.png' in caplog.text


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
            storyboard_prompt='现成 prompt',
            character_reference_ids=[12],
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
        '_resolve_ref_image_paths',
        lambda story_id, ref_ids: ['https://cdn.example.com/ref-12.png'],
    )
    monkeypatch.setattr(video_chapter_pipeline, 'ensure_local_media_path', lambda value, kind: 'C:/tmp/ref-12.png' if kind == 'manga' else None)
    monkeypatch.setattr(video_chapter_pipeline, '_pick_style_anchor_image', lambda workflow_id, shot_id: None)

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key', ref_asset_ids=[12]))

    assert captured['ref_image_paths'] == ['C:/tmp/ref-12.png']
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
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_ref_image_paths', lambda story_id, ref_ids: ['https://cdn.example.com/character-86.png'])
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: None)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: None)
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
        'https://cdn.example.com/character-86.png',
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
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url='https://cdn.example.com/style.png'),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_ref_image_paths', lambda story_id, ref_ids: ['https://cdn.example.com/character-86.png'])
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: None)
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: 'C:/tmp/style.png')
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
    assert '[video_submit]   参考图 2 [character][remote]: https://cdn.example.com/character-86.png' in caplog.text
    assert '[video_submit]   参考图 3 [style][remote]: https://cdn.example.com/style.png' in caplog.text


def test_regenerate_shot_video_prefers_remote_urls_for_all_reference_images(monkeypatch):
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
        lambda workflow_id: SimpleNamespace(id=workflow_id, story_id=901, chapter_id=440, style_reference_image_url='https://cdn.example.com/style.png'),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_ref_image_paths', lambda story_id, ref_ids: ['https://cdn.example.com/character-86.png'])
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_storyboard_local_path', lambda url: 'C:/tmp/storyboard-194.png')
    monkeypatch.setattr(video_chapter_pipeline, 'resolve_reference_input', lambda value, kind: value)
    monkeypatch.setattr(video_chapter_pipeline, '_resolve_style_ref_local_path', lambda value: 'C:/tmp/style.png')

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

    asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86, 194]))

    assert captured['reference_images'] == [
        'https://cdn.example.com/storyboard-194.png',
        'https://cdn.example.com/character-86.png',
        'https://cdn.example.com/style.png',
    ]


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


def test_shot_video_prompt_template_no_longer_uses_10s_segments():
    from services import video_chapter_prompts as prompts

    assert "7-10秒" not in prompts.SHOT_VIDEO_SYSTEM_PROMPT
    assert "8.5-10秒" not in prompts.SHOT_VIDEO_SYSTEM_PROMPT


def test_storyboard_and_video_prompts_share_same_segment_schema():
    from services import video_chapter_prompts as prompts

    assert "segments" in prompts.SHOT_VIDEO_USER_TEMPLATE
    assert "storyboard_prompt" in prompts.SHOT_VIDEO_SYSTEM_PROMPT or "storyboard_prompt" in prompts.SHOT_VIDEO_USER_TEMPLATE
    assert "video_prompt" in prompts.SHOT_VIDEO_USER_TEMPLATE
    assert "段落数量由导演判断" in prompts.SHOT_VIDEO_USER_TEMPLATE


def test_storyboard_director_prompt_no_longer_uses_10s_beats():
    from services import video_chapter_prompts as prompts

    assert "0-3 秒" not in prompts.STORYBOARD_DIRECTOR_SYSTEM_PROMPT
    assert "3-7 秒" not in prompts.STORYBOARD_DIRECTOR_SYSTEM_PROMPT
    assert "7-10 秒" not in prompts.STORYBOARD_DIRECTOR_SYSTEM_PROMPT


def test_shot_parse_prompt_mentions_15_second_capacity_modeling():
    from services import video_chapter_prompts as prompts

    assert "15 秒" in prompts.SHOT_PARSE_SYSTEM_PROMPT
    assert "10 秒镜头" not in prompts.SHOT_PARSE_SYSTEM_PROMPT
    assert "把故事改编成事件" in prompts.SHOT_PARSE_SYSTEM_PROMPT
    assert "分镜数量必须尽可能少" in prompts.SHOT_PARSE_SYSTEM_PROMPT


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


def test_regenerate_shot_video_rebuilds_legacy_10s_prompt(monkeypatch):
    captured: dict[str, object] = {}

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

    async def fake_generate_shot_video_prompt_ai(payload, api_key=None, **kwargs):
        captured['payload'] = payload
        captured['storyboard_prompt'] = kwargs.get('storyboard_prompt')
        return '新的15秒视频提示词'

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

            return _Query()

        def get(self, model, pk):
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, 'SessionLocal', lambda: _Db())
    monkeypatch.setattr(video_chapter_pipeline.deepseek_service, 'generate_shot_video_prompt_ai', fake_generate_shot_video_prompt_ai)
    monkeypatch.setattr(video_chapter_pipeline, '_poll_video_job', fake_poll_video_job)
    monkeypatch.setattr(video_chapter_pipeline.video_gen_service, 'submit_video_job', fake_submit_video_job)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_video(194, api_key='video-key', ref_asset_ids=[86]))

    assert captured['payload']['scene_location'] == '办公室'
    assert result is not None


def test_poll_video_job_defaults_to_7200_seconds():
    assert video_chapter_pipeline._poll_video_job.__defaults__[3] == 7200


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


def test_start_workflow_background_omits_task_timeout(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        "get_workflow",
        lambda workflow_id: SimpleNamespace(
            id=workflow_id, chapter_id=12, story_id=34,
            source_text="正文", character_reference_ids=[], video_style="写实",
        ),
    )

    async def fake_submit_task(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(video_chapter_pipeline.task_manager, "submit_task", fake_submit_task)

    asyncio.run(video_chapter_pipeline.start_workflow_background(77, api_key="video-key"))

    assert captured["timeout"] is None


def test_api_create_chapter_workflow_does_not_auto_start(monkeypatch):
    """创建工作流后不自动启动流水线——用户手动触发各阶段。"""
    db = _FakeDb()
    captured: dict[str, object] = {}

    async def fake_start_background(**kwargs):
        captured.update(kwargs)
        return f"chapter_video_77"

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router,
        "_require_chapter_for_user",
        lambda chapter_id, user, db_session: SimpleNamespace(id=chapter_id, story_id=900, novel_content="章节正文"),
    )
    monkeypatch.setattr(video_router, "create_chapter_workflow", lambda **kw: SimpleNamespace(id=77))
    monkeypatch.setattr(video_router, "start_workflow_background", fake_start_background)
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: SimpleNamespace(id=workflow_id))
    monkeypatch.setattr(video_router, "init_db", lambda **kw: None, raising=False)

    result = asyncio.run(
        video_router.api_create_chapter_workflow(
            body=ChapterVideoWorkflowCreate(chapter_id=440, character_reference_ids=[11, 22], video_style="写实电影感"),
            request=SimpleNamespace(), db=db,
        )
    )

    assert captured == {}, \
        f"不应自动启动流水线，但 start_workflow_background 被调用: {captured}"
    assert result.id == 77


def test_shot_video_user_prompt_includes_storyboard_prompt():
    from services.video_chapter_prompts import build_shot_video_user_prompt

    result = build_shot_video_user_prompt(
        scene_location="天台上",
        time_of_day="夜",
        characters=["少年", "少女"],
        story_summary="两人在天台望月",
        camera_plan="远景缓慢推近",
        motion_plan="站定望月",
        emotion_plan="孤独转静谧",
        continuity_notes="保持角色一致",
        storyboard_prompt="少年和少女站在城市天台上仰望巨大圆月",
    )

    assert "少年和少女站在城市天台上仰望巨大圆月" in result


def test_api_parse_chapter_shots_refreshes_source_text_from_db(monkeypatch):
    """parse 端点应从 DB 读取最新章节内容，而非使用工作流创建时的快照。"""
    db_captured: dict[str, object] = {}

    class _ParseRefreshDb:
        def __init__(self):
            self.wf = SimpleNamespace(id=11, chapter_id=444, story_id=900, source_text="旧的快照内容")
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

    async def fake_parse(**kwargs):
        db_captured["source_text"] = kwargs.get("source_text", "")
        return {"workflow_status": "shots_ready", "shot_count": 3}

    monkeypatch.setattr(video_router, "parse_chapter_shots", fake_parse)

    result = asyncio.run(
        video_router.api_parse_chapter_shots(
            workflow_id=11, request=SimpleNamespace(), db=db,
        )
    )

    assert db_captured.get("source_text") == "新的章节正文", \
        f"应使用 DB 最新章节内容，而非旧快照，实际: {db_captured.get('source_text')}"
    assert db.wf.source_text == "新的章节正文", \
        "工作流 source_text 应从 DB 同步更新"
    assert db.commit_called, "应提交 source_text 更新"


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
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "fake-key")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            video_router.api_parse_chapter_shots(
                workflow_id=11, request=SimpleNamespace(), db=db,
            )
        )

    assert exc_info.value.status_code == 400
    assert "章节正文为空" in exc_info.value.detail


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
