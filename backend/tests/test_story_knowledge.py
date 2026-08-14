import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import (
    AgentContextReceipt,
    Chapter,
    DeconstructionChapter,
    DeconstructionWork,
    StaleKnowledgeContextError,
    Story,
    StoryDeconstructionRef,
    StoryKnowledgeCategory,
    StoryKnowledgeEntity,
    StoryKnowledgeFact,
    StoryKnowledgeResource,
    StoryPlotThread,
    reset_agent_knowledge_revision_guard,
    set_agent_knowledge_revision_guard,
)
from services.story_knowledge import (
    StoryKnowledgeConflictError,
    apply_chapter_context_pack,
    bump_story_knowledge_revision,
    build_agent_story_manifest,
    create_story_knowledge_category,
    create_story_knowledge_item,
    delete_story_knowledge_category,
    delete_story_knowledge_item,
    list_story_knowledge,
    resolve_story_context,
    resolve_chapter_context_pack,
    search_story_knowledge,
    sync_story_knowledge_from_legacy,
    update_story_knowledge_category,
    update_story_knowledge_item,
    validate_context_receipt,
)
from services.story_state import build_story_bible_compact, has_active_writing_reference
import services.knowledge_ai_sync as knowledge_ai_sync
from services.knowledge_ai_sync import SYNC_SCHEMA_VERSION, _build_sources, _collect_source_results, _extract_source, _merge_results, _normalize_sync_result, _parse_sync_json, _result_schema_version, _retry_markers
from routers.deconstruct_library import _refresh_library_reference_materials


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _story(db, title: str = "测试长篇") -> Story:
    story = Story(
        title=title,
        description="一段不应直接进入 Agent 初始上下文的长描述",
        tags={"type": "玄幻"},
        characters=[{"name": "陈玄", "role": "主角", "motivation": "寻找遗迹真相"}],
        story_bible={"creative_brief": {"core_hook": "残卷指向失落文明"}},
        story_memory={"continuity_facts": ["陈玄持有残卷"], "open_loops": ["残卷来源未知"]},
        outline={
            "summary": "围绕残卷展开的长篇故事",
            "three_acts": [{
                "act": "1",
                "title": "入局",
                "summary": "发现线索",
                "chapters": [
                    {"chapter_number": 1, "title": "残卷", "goal": "取得残卷"},
                    {"chapter_number": 2, "title": "试探", "goal": "确认价值"},
                ],
            }],
        },
    )
    db.add(story)
    db.flush()
    db.add(Chapter(
        story_id=story.id,
        chapter_number=1,
        title="残卷",
        novel_content="陈玄收起残卷。" * 100,
        memory_summary={"summary": "陈玄取得残卷", "ending_scene": "他决定前往灰市"},
    ))
    db.commit()
    return story


def test_ai_sync_only_scans_changed_story_sources():
    db = _session()
    story = _story(db)

    first_sources, fingerprints, static_hash = _build_sources(db, story, {})
    assert any(source["source_id"].startswith("story:") for source in first_sources)
    assert any(source["source_id"].startswith("chapter:") for source in first_sources)

    unchanged_sources, _, _ = _build_sources(db, story, {"chapter_fingerprints": fingerprints, "static_hash": static_hash, "sync_schema_version": SYNC_SCHEMA_VERSION})
    assert unchanged_sources == []

    chapter = db.query(Chapter).filter_by(story_id=story.id).one()
    chapter.novel_content = f"{chapter.novel_content}新增线索"
    db.commit()
    changed_sources, _, _ = _build_sources(db, story, {"chapter_fingerprints": fingerprints, "static_hash": static_hash, "sync_schema_version": SYNC_SCHEMA_VERSION})
    assert changed_sources
    assert all(source["source_id"].startswith("chapter:") for source in changed_sources)


def test_ai_sync_rescans_renumbered_chapter():
    db = _session()
    story = _story(db)
    _, fingerprints, static_hash = _build_sources(db, story, {})

    chapter = db.query(Chapter).filter_by(story_id=story.id).one()
    chapter.chapter_number = 8
    db.commit()

    changed_sources, _, _ = _build_sources(
        db,
        story,
        {"chapter_fingerprints": fingerprints, "static_hash": static_hash, "sync_schema_version": SYNC_SCHEMA_VERSION},
    )
    assert changed_sources
    assert all(source["source_id"].startswith(f"chapter:{chapter.id}:") for source in changed_sources)


def test_ai_sync_rescans_changed_story_tags():
    db = _session()
    story = _story(db)
    _, fingerprints, static_hash = _build_sources(db, story, {})

    story.tags = {"type": "悬疑"}
    db.commit()

    changed_sources, _, _ = _build_sources(
        db,
        story,
        {"chapter_fingerprints": fingerprints, "static_hash": static_hash, "sync_schema_version": SYNC_SCHEMA_VERSION},
    )
    assert changed_sources
    assert all(source["source_id"].startswith(f"story:{story.id}:static:") for source in changed_sources)


def test_ai_sync_parser_accepts_fences_trailing_text_and_trailing_commas():
    fenced = """```json
    {"entities": [{"entity_key": "character:chen", "canonical_name": "陈玄",}], "facts": [], "plot_threads": []}
    ```"""
    parsed = _parse_sync_json(fenced)
    assert parsed["entities"][0]["canonical_name"] == "陈玄"

    with_trailing_text = '{"entities": [], "facts": [], "plot_threads": []}\n同步完成。'
    assert _parse_sync_json(with_trailing_text)["facts"] == []


def test_ai_sync_normalizes_string_encoded_arrays_and_items():
    normalized = _normalize_sync_result({
        "entities": '[{"entity_key":"character:chen","canonical_name":"陈玄"}]',
        "facts": ['{"subject_key":"character:chen","predicate":"持有"}'],
        "plotThreads": {"thread_key": "scroll", "title": "残卷来源"},
    })
    assert normalized["entities"][0]["canonical_name"] == "陈玄"
    assert normalized["facts"][0]["predicate"] == "持有"
    assert normalized["plot_threads"][0]["title"] == "残卷来源"


def test_ai_sync_rejects_json_without_required_arrays():
    with pytest.raises(ValueError, match="缺少字段"):
        _normalize_sync_result({})

    with pytest.raises(ValueError, match="必须是数组"):
        _normalize_sync_result({"entities": 1, "facts": [], "plot_threads": []})

    with pytest.raises(ValueError, match="缺少必填字段"):
        _normalize_sync_result({"entities": [], "facts": [{"predicate": "持有"}], "plot_threads": []})

    with pytest.raises(ValueError, match="无法解析"):
        _normalize_sync_result({"entities": [], "facts": ["not-json"], "plot_threads": []})

    with pytest.raises(ValueError, match="缺少必填字段"):
        _normalize_sync_result({
            "entities": [],
            "facts": [{"subject_key": ["character:chen"], "predicate": {"name": "持有"}}],
            "plot_threads": [],
        })


def test_ai_sync_keeps_failed_sources_pending_for_next_run():
    fingerprints = {"11": "chapter-11", "12": "chapter-12"}
    retry_fingerprints, retry_static_hash = _retry_markers(
        fingerprints,
        "new-static-hash",
        {"static_hash": "old-static-hash"},
        {"chapter:11:1", "story:7:static:0"},
    )

    assert retry_fingerprints == {"12": "chapter-12"}
    assert retry_static_hash == "old-static-hash"


def test_ai_sync_does_not_finish_schema_upgrade_after_partial_failure():
    assert _result_schema_version({}, True) is None
    assert _result_schema_version({"sync_schema_version": 2}, True) == 2
    assert _result_schema_version({}, False) == SYNC_SCHEMA_VERSION


def test_ai_sync_retries_invalid_json_response(monkeypatch):
    class FakeResponse:
        def __init__(self, content):
            self.text = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False)
            self.status_code = 200
            self.headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def post(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse('{"entities": [')
            return FakeResponse('{"entities": [], "facts": [], "plot_threads": []}')

    monkeypatch.setattr(knowledge_ai_sync, "runtime_model", lambda: "test-model")
    monkeypatch.setattr(knowledge_ai_sync, "runtime_base_url", lambda: "http://example.invalid")
    monkeypatch.setattr(knowledge_ai_sync, "_deepseek_auth_headers", lambda _api_key: {})
    client = FakeClient()
    result = asyncio.run(_extract_source(
        client,
        asyncio.Semaphore(1),
        {"source_id": "chapter:1:0", "chapter": 1, "text": "陈玄取得残卷"},
        {"entities": [], "facts": [], "threads": []},
        None,
    ))
    assert client.calls == 2
    assert result == {
        "entities": [],
        "facts": [],
        "plot_threads": [],
        "_source_id": "chapter:1:0",
        "_source_chapter": 1,
    }


def test_ai_sync_collection_timeout_preserves_completed_results(monkeypatch):
    async def fake_extract(_client, _semaphore, source, _manifest, _api_key):
        if source["source_id"] == "chapter:2:0":
            await asyncio.Event().wait()
        return {"entities": [], "facts": [], "plot_threads": [], "_source_id": source["source_id"]}

    monkeypatch.setattr(knowledge_ai_sync, "_extract_source", fake_extract)
    monkeypatch.setattr(knowledge_ai_sync, "SYNC_COLLECTION_TIMEOUT", 0.01)
    sources = [
        {"source_id": "chapter:1:0", "chapter": 1, "text": "已完成"},
        {"source_id": "chapter:2:0", "chapter": 2, "text": "持续等待"},
    ]

    results, failures, failed_source_ids, timed_out = asyncio.run(_collect_source_results(
        SimpleNamespace(),
        sources,
        {"entities": [], "facts": [], "threads": []},
        None,
        None,
        asyncio.Semaphore(2),
    ))

    assert [result["_source_id"] for result in results] == ["chapter:1:0"]
    assert failed_source_ids == {"chapter:2:0"}
    assert failures == ["来源 chapter:2:0 超过同步时间预算"]
    assert timed_out is True


def test_ai_sync_merge_preserves_manual_entities_and_updates_stable_ai_records():
    db = _session()
    story = _story(db)
    manual = StoryKnowledgeEntity(story_id=story.id, entity_key="character:chen-xuan", entity_type="character", canonical_name="人工陈玄", source_type="manual")
    db.add(manual)
    db.commit()
    payload = [{
        "_source_id": "chapter:1:0",
        "entities": [{"entity_key": "character:chen-xuan", "canonical_name": "AI 陈玄", "entity_type": "character"}],
        "facts": [{"stable_key": "chen-holds-scroll", "subject_key": "character:chen-xuan", "predicate": "持有", "value_text": "陈玄持有残卷", "valid_from_chapter": 1}],
        "plot_threads": [{"thread_key": "scroll-origin", "title": "残卷来源", "setup_chapter": 1, "status": "open"}],
    }]

    first = _merge_results(db, story, payload)
    second = _merge_results(db, story, payload)

    db.refresh(manual)
    assert manual.canonical_name == "人工陈玄"
    assert first == {
        "entities": 0,
        "facts": 1,
        "plot_threads": 1,
        "archived_facts": 0,
        "archived_plot_threads": 0,
    }
    assert second == first
    assert db.query(StoryKnowledgeFact).filter_by(story_id=story.id).count() == 1
    assert db.query(StoryPlotThread).filter_by(story_id=story.id).count() == 1


def test_ai_sync_uses_source_chapter_when_model_omits_time_fields():
    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id).one()
    payload = [{
        "_source_id": f"chapter:{chapter.id}:0",
        "_source_chapter": 7,
        "entities": [{
            "entity_key": "character:newcomer",
            "canonical_name": "新登场者",
            "entity_type": "character",
        }],
        "facts": [{
            "stable_key": "chen-realm",
            "subject_key": "character:chen-xuan",
            "predicate": "境界",
            "value_text": "炼体七重",
        }],
        "plot_threads": [{
            "thread_key": "realm-secret",
            "title": "境界异变",
            "status": "open",
        }],
    }]

    _merge_results(db, story, payload)

    fact = db.query(StoryKnowledgeFact).filter_by(story_id=story.id, predicate="境界").one()
    thread = db.query(StoryPlotThread).filter_by(story_id=story.id, thread_key="realm-secret").one()
    entity = db.query(StoryKnowledgeEntity).filter_by(story_id=story.id, entity_key="character:newcomer").one()
    assert entity.first_chapter == 7
    assert fact.valid_from_chapter == 7
    assert fact.source_chapter_id == chapter.id
    assert thread.setup_chapter == 7


def test_ai_sync_fact_identity_is_stable_across_source_chunks():
    db = _session()
    story = _story(db)
    fact = {
        "stable_key": "chen-holds-scroll",
        "subject_key": "character:chen-xuan",
        "predicate": "持有",
        "value_text": "陈玄持有残卷",
        "valid_from_chapter": 1,
    }

    _merge_results(db, story, [{"_source_id": "chapter:1:0", "entities": [], "facts": [fact], "plot_threads": []}])
    _merge_results(db, story, [{"_source_id": "chapter:1:2", "entities": [], "facts": [fact], "plot_threads": []}])

    rows = db.query(StoryKnowledgeFact).filter_by(story_id=story.id).all()
    assert len(rows) == 1
    assert rows[0].source_chapter_id == 1


def test_ai_sync_entity_chapter_range_is_merged_across_sources():
    db = _session()
    story = _story(db)
    later = {
        "entity_key": "character:chen-xuan",
        "canonical_name": "陈玄",
        "aliases_json": ["玄子"],
        "first_chapter": 10,
        "last_chapter": 12,
    }
    earlier = {
        "entity_key": "character:chen-xuan",
        "canonical_name": "陈玄",
        "aliases_json": ["陈公子"],
        "first_chapter": 1,
        "last_chapter": 3,
    }

    _merge_results(db, story, [
        {"_source_id": "chapter:10:0", "entities": [later], "facts": [], "plot_threads": []},
        {"_source_id": "chapter:1:0", "entities": [earlier], "facts": [], "plot_threads": []},
    ])

    row = db.query(StoryKnowledgeEntity).filter_by(story_id=story.id).one()
    assert row.first_chapter == 1
    assert row.last_chapter == 12
    assert row.aliases_json == ["玄子", "陈公子"]


def test_ai_sync_archives_removed_facts_after_complete_source_refresh():
    db = _session()
    story = _story(db)
    fact = {
        "stable_key": "chen-holds-scroll",
        "subject_key": "character:chen-xuan",
        "predicate": "持有",
        "value_text": "陈玄持有残卷",
    }
    _merge_results(
        db,
        story,
        [{"_source_id": "chapter:1:0", "entities": [], "facts": [fact], "plot_threads": []}],
        reconcile_scopes={"chapter:1"},
    )

    result = _merge_results(
        db,
        story,
        [{"_source_id": "chapter:1:0", "entities": [], "facts": [], "plot_threads": []}],
        reconcile_scopes={"chapter:1"},
    )

    row = db.query(StoryKnowledgeFact).filter_by(story_id=story.id).one()
    assert row.status == "archived"
    assert result["archived_facts"] == 1


def test_ai_sync_archives_removed_threads_after_complete_source_refresh():
    db = _session()
    story = _story(db)
    thread = {"thread_key": "scroll-origin", "title": "残卷来源", "status": "open"}
    _merge_results(
        db,
        story,
        [{"_source_id": "chapter:1:0", "entities": [], "facts": [], "plot_threads": [thread]}],
        reconcile_scopes={"chapter:1"},
    )

    result = _merge_results(
        db,
        story,
        [{"_source_id": "chapter:1:0", "entities": [], "facts": [], "plot_threads": []}],
        reconcile_scopes={"chapter:1"},
    )

    row = db.query(StoryPlotThread).filter_by(story_id=story.id, thread_key="scroll-origin").one()
    assert row.status == "archived"
    assert result["archived_plot_threads"] == 1


def test_ai_sync_does_not_archive_failed_source_scope():
    db = _session()
    story = _story(db)
    fact = {
        "stable_key": "chen-holds-scroll",
        "subject_key": "character:chen-xuan",
        "predicate": "持有",
        "value_text": "陈玄持有残卷",
    }
    _merge_results(
        db,
        story,
        [{"_source_id": "chapter:1:0", "entities": [], "facts": [fact], "plot_threads": []}],
        reconcile_scopes={"chapter:1"},
    )

    _merge_results(db, story, [], reconcile_scopes=set())

    row = db.query(StoryKnowledgeFact).filter_by(story_id=story.id).one()
    assert row.status == "active"


def test_ai_sync_archives_deleted_chapter_fact_after_foreign_key_is_cleared():
    db = _session()
    story = _story(db)
    fact = {
        "stable_key": "chen-holds-scroll",
        "subject_key": "character:chen-xuan",
        "predicate": "持有",
        "value_text": "陈玄持有残卷",
    }
    _merge_results(
        db,
        story,
        [{"_source_id": "chapter:1:0", "entities": [], "facts": [fact], "plot_threads": []}],
    )
    row = db.query(StoryKnowledgeFact).filter_by(story_id=story.id).one()
    row.source_chapter_id = None
    db.commit()

    result = _merge_results(db, story, [], deleted_chapter_ids={1})

    db.refresh(row)
    assert row.status == "archived"
    assert result["archived_facts"] == 1


def test_ai_sync_full_schema_upgrade_archives_unconfirmed_legacy_fact():
    db = _session()
    story = _story(db)
    legacy = StoryKnowledgeFact(
        story_id=story.id,
        subject_key="character:chen-xuan",
        predicate="持有",
        value_text="已经从正文删除的旧事实",
        source_type="agent",
        source_id="ai_sync:fact:legacy-digest",
        status="active",
    )
    db.add(legacy)
    db.commit()

    result = _merge_results(db, story, [], archive_legacy=True)

    db.refresh(legacy)
    assert legacy.status == "archived"
    assert result["archived_facts"] == 1


def test_manifest_is_lightweight_and_requires_database_resolution():
    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id).one()

    manifest = build_agent_story_manifest(story, chapter)

    assert f"作品 ID: {story.id}" in manifest
    assert "resolve_story_context" in manifest
    assert story.description not in manifest
    assert "围绕残卷展开的长篇故事" not in manifest


def test_stale_writing_reference_is_excluded_without_an_active_source():
    stale_bible = {
        "reference_author_profile": {
            "style_profile": {"sentence": {"general": "不应继续生效的旧风格"}},
        },
        "reference_author_report": "不应继续注入的旧报告",
        "reference_style_samples": [{"snippet": "旧样本"}],
        "deconstruction_7": {},
    }

    compact = build_story_bible_compact(stale_bible)

    assert has_active_writing_reference(stale_bible) is False
    assert "reference_author_profile" not in compact
    assert "reference_author_report" not in compact
    assert "reference_style_samples" not in compact


@pytest.mark.parametrize(
    "source_marker",
    [
        {"deconstruction_7": {"title": "匿名参考作品"}},
        {"deconstruction": {"result_id": 7, "source": {"title": "本作品拆书结果"}}},
        {"reference_author_profile": {"manual_override": True}},
    ],
)
def test_active_writing_reference_is_included_for_import_or_manual_rules(source_marker):
    profile = {
        "style_profile": {"sentence": {"general": "用户确认的写作风格"}},
        **source_marker.get("reference_author_profile", {}),
    }
    story_bible = {
        **source_marker,
        "reference_author_profile": profile,
        "reference_author_report": "用户确认的写作报告",
    }

    compact = build_story_bible_compact(story_bible)

    assert has_active_writing_reference(story_bible) is True
    assert compact["reference_author_profile"] == profile
    assert compact["reference_author_report"] == "用户确认的写作报告"


def test_deepseek_snapshot_ignores_stale_reference_but_uses_active_reference():
    from services.deepseek import _build_story_snapshot

    stale_bible = {
        "reference_author_profile": {"style_profile": {"sentence": {"general": "旧风格"}}},
        "reference_author_report": "旧报告",
        "reference_style_samples": [{"snippet": "旧样本"}],
    }
    stale_snapshot = _build_story_snapshot({"story_bible": stale_bible})
    active_snapshot = _build_story_snapshot({
        "story_bible": {
            **stale_bible,
            "reference_author_profile": {
                "manual_override": True,
                "style_profile": {"sentence": {"general": "人工确认风格"}},
            },
            "reference_author_report": "人工确认报告",
        },
    })

    assert "旧风格" not in stale_snapshot
    assert "旧报告" not in stale_snapshot
    assert "旧样本" not in stale_snapshot
    assert "人工确认风格" in active_snapshot
    assert "人工确认报告" in active_snapshot


def test_chapter_writer_context_includes_complete_active_reference_package():
    db = _session()
    story = _story(db)
    story.story_bible = {
        **story.story_bible,
        "deconstruction_7": {"title": "匿名参考作品"},
        "reference_author_profile": {"style_profile": {"sentence": {"general": "短句推进"}}},
        "reference_author_report": "对话推动冲突",
        "reference_style_samples": [{"snippet": "他停下脚步。"}],
        "learned_techniques": [{"name": "场景转折"}],
        "reference_plots": [{"name": "误判反转"}],
        "reference_rhythm": {"opening": "异常开场"},
        "reference_emotion_modules": {"cycle": "压迫-反击"},
    }
    db.commit()

    result = resolve_story_context(db, story=story, task_type="chapter_writer", chapter_number=2)
    style_profile = result["sections"]["style_profile"]

    assert style_profile["reference_author_profile"]["style_profile"]["sentence"]["general"] == "短句推进"
    assert style_profile["reference_author_report"] == "对话推动冲突"
    assert style_profile["reference_style_samples"] == [{"snippet": "他停下脚步。"}]
    assert style_profile["learned_techniques"] == [{"name": "场景转折"}]
    assert style_profile["reference_plots"] == [{"name": "误判反转"}]
    assert style_profile["reference_rhythm"] == {"opening": "异常开场"}
    assert style_profile["reference_emotion_modules"] == {"cycle": "压迫-反击"}


def test_chapter_writer_context_excludes_future_plot_guidance_but_keeps_writing_rules():
    db = _session()
    story = _story(db)
    story.story_bible = {
        **story.story_bible,
        "writing_guidance": {
            "开书策略": "第1章落凡，第2章捡漏，第3章擂台",
            "章节密度策略": "每5章切换一次支线",
            "中段驱动力": "秘境探索与资源积累",
            "后期方向": "终极补天决战",
            "推荐情节模式": "秘境开荒",
            "避免的模式": "禁止主角降智",
            "核心铁律": "每章至少一个主动决策",
        },
    }
    db.commit()

    result = resolve_story_context(db, story=story, task_type="chapter_writer", chapter_number=1)
    guidance = result["sections"]["style_profile"]["writing_guidance"]

    assert guidance == {
        "避免的模式": "禁止主角降智",
        "核心铁律": "每章至少一个主动决策",
    }


def test_library_reference_refresh_falls_back_to_remaining_work():
    db = _session()
    first = DeconstructionWork(
        owner_user_id=1,
        title="参考作品甲",
        platform="qidian",
        author_style_profile={"sampled_chapters": [1], "style_profile": {"sentence": {"general": "甲风格"}}},
        author_style_report_markdown="甲报告",
    )
    second = DeconstructionWork(
        owner_user_id=1,
        title="参考作品乙",
        platform="qidian",
        author_style_profile={"sampled_chapters": [1], "style_profile": {"sentence": {"general": "乙风格"}}},
        author_style_report_markdown="乙报告",
    )
    db.add_all([first, second])
    db.flush()
    db.add_all([
        DeconstructionChapter(work_id=first.id, chapter_number=1, content="甲样本"),
        DeconstructionChapter(work_id=second.id, chapter_number=1, content="乙样本"),
    ])
    db.commit()
    story_bible = {
        "reference_author_profile": second.author_style_profile,
        "reference_author_report": "乙报告",
        "reference_style_samples": [{"snippet": "乙样本"}],
    }

    _refresh_library_reference_materials(db, story_bible, first)

    assert story_bible["reference_author_profile"] == first.author_style_profile
    assert story_bible["reference_author_report"] == "甲报告"
    assert story_bible["reference_style_samples"] == [{"chapter": 1, "snippet": "甲样本"}]


def test_deleting_referenced_work_cleans_marker_and_restores_remaining_source(monkeypatch):
    import routers.deconstruct_library as library_router

    db = _session()
    story = _story(db)
    first = DeconstructionWork(
        owner_user_id=1,
        title="参考作品甲",
        platform="qidian",
        decon_status="completed",
        author_style_profile={"style_profile": {"sentence": {"general": "甲风格"}}},
        author_style_report_markdown="甲报告",
    )
    second = DeconstructionWork(
        owner_user_id=1,
        title="参考作品乙",
        platform="qidian",
        decon_status="completed",
        author_style_profile={"style_profile": {"sentence": {"general": "乙风格"}}},
        author_style_report_markdown="乙报告",
    )
    db.add_all([first, second])
    db.flush()
    db.add_all([
        StoryDeconstructionRef(story_id=story.id, work_id=first.id),
        StoryDeconstructionRef(story_id=story.id, work_id=second.id),
    ])
    story.story_bible = {
        f"deconstruction_{first.id}": {"title": first.title},
        f"deconstruction_{second.id}": {"title": second.title},
        "reference_author_profile": second.author_style_profile,
        "reference_author_report": "乙报告",
    }
    db.commit()
    deleted_work_id = second.id
    monkeypatch.setattr(library_router, "_require_user", lambda request, session: SimpleNamespace(id=1))

    asyncio.run(library_router.delete_deconstruction_work(deleted_work_id, None, db))
    db.refresh(story)

    assert db.get(DeconstructionWork, deleted_work_id) is None
    assert f"deconstruction_{deleted_work_id}" not in story.story_bible
    assert story.story_bible["reference_author_profile"] == first.author_style_profile
    assert story.story_bible["reference_author_report"] == "甲报告"


def test_framework_context_includes_all_active_reference_sections():
    from main import _build_framework_context

    db = _session()
    story = _story(db)
    story.story_bible = {
        **story.story_bible,
        "reference_author_profile": {"manual_override": True},
        "learned_techniques": [{"name": "场景转折"}],
        "reference_plots": [{"name": "误判反转"}],
        "reference_rhythm": {"opening": "异常开场"},
        "reference_emotion_modules": {"cycle": "压迫-反击"},
    }

    context = _build_framework_context(story)

    assert "参考写作手法" in context and "场景转折" in context
    assert "参考剧情模式" in context and "误判反转" in context
    assert "参考节奏控制" in context and "异常开场" in context
    assert "参考情绪模块" in context and "压迫-反击" in context


def test_resolver_combines_legacy_projection_and_database_knowledge():
    db = _session()
    story = _story(db)
    db.add_all([
        StoryKnowledgeEntity(
            story_id=story.id,
            entity_key="character:chen-xuan",
            entity_type="character",
            canonical_name="陈玄",
            profile_json={"location": "灰市", "realm": "炼体初期"},
            importance=100,
        ),
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:chen-xuan",
            predicate="owns",
            object_key="item:fragment",
            value_text="持有秘境残卷",
            valid_from_chapter=1,
        ),
        StoryPlotThread(
            story_id=story.id,
            thread_key="mystery:fragment-origin",
            thread_type="mystery",
            title="残卷来源",
            description="残卷属于失落仙道文明",
            setup_chapter=1,
            expected_payoff_from=20,
            expected_payoff_to=30,
            priority=90,
        ),
        StoryKnowledgeResource(
            story_id=story.id,
            resource_type="style_profile",
            resource_key="platform:qidian",
            title="起点创作档案",
            content_json={"pacing": "冲突前置", "paragraph": "短段落"},
            importance=80,
        ),
    ])
    db.commit()

    result = resolve_story_context(
        db,
        story=story,
        task_type="chapter_writer",
        chapter_number=2,
        owner_user_id=7,
        run_id="run-1",
    )

    assert result["task_type"] == "chapter_writer"
    assert result["sections"]["chapter_plan"]["current"]["title"] == "试探"
    assert set(result["sections"]["chapter_plan"]) == {"current"}
    assert "characters" not in result["sections"]
    # 正文写作必须携带连续性记忆，保证章节开头衔接上一章（修复：chapter_writer 补上 story_memory 分区）
    assert "story_memory" in result["sections"]
    assert result["sections"]["story_memory"]["continuity_facts"] == ["陈玄持有残卷"]
    assert result["sections"]["recent_chapters"][0]["chapter_number"] == 1
    assert result["sections"]["entities"][0]["key"] == "character:chen-xuan"
    assert any(item["predicate"] == "owns" for item in result["sections"]["facts"])
    assert result["sections"]["open_threads"][0]["key"] == "mystery:fragment-origin"
    assert result["sections"]["style_profile"][0]["key"] == "platform:qidian"
    receipt = db.query(AgentContextReceipt).filter_by(receipt_id=result["receipt_id"]).one()
    assert receipt.knowledge_revision == story.knowledge_revision
    assert receipt.context_hash


def test_fact_validity_and_story_isolation_are_enforced():
    db = _session()
    story = _story(db, "作品甲")
    other = _story(db, "作品乙")
    db.add_all([
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:chen-xuan",
            predicate="location",
            value_text="旧城",
            valid_from_chapter=1,
            valid_to_chapter=3,
        ),
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:chen-xuan",
            predicate="location",
            value_text="灰市",
            valid_from_chapter=4,
        ),
        StoryKnowledgeEntity(
            story_id=other.id,
            entity_key="secret:other-story",
            entity_type="secret",
            canonical_name="其他作品秘密",
        ),
    ])
    db.commit()

    result = resolve_story_context(db, story=story, task_type="chapter_writer", chapter_number=5)
    locations = [item["value"] for item in result["sections"]["facts"] if item["predicate"] == "location"]

    assert locations == ["灰市"]
    assert all(item.get("key") != "secret:other-story" for item in result["sections"]["entities"])


def test_chapter_writer_excludes_future_source_records_and_keeps_latest_state():
    db = _session()
    story = _story(db)
    first_chapter = db.query(Chapter).filter_by(story_id=story.id, chapter_number=1).one()
    second_chapter = Chapter(story_id=story.id, chapter_number=2, title="试探", novel_content="债务已经还清。")
    db.add(second_chapter)
    db.flush()
    db.add_all([
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:chen-xuan",
            predicate="债务状态",
            value_text="债务尚未还清",
            valid_from_chapter=1,
            source_type="agent",
            source_chapter_id=first_chapter.id,
        ),
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:chen-xuan",
            predicate="债务状态",
            value_text="债务已经还清",
            valid_from_chapter=2,
            source_type="agent",
            source_chapter_id=second_chapter.id,
        ),
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:chen-xuan",
            predicate="后期境界",
            value_text="陈玄突破筑基境",
            source_type="agent",
            source_id=f"ai_sync:v3:fact:c{second_chapter.id}:future",
            source_chapter_id=second_chapter.id,
        ),
        StoryKnowledgeEntity(
            story_id=story.id,
            entity_key="character:future-elder",
            entity_type="character",
            canonical_name="未来长老",
            first_chapter=2,
            source_type="agent",
            source_id=f"ai_sync:v3:entity:c{second_chapter.id}:future",
        ),
        StoryKnowledgeEntity(
            story_id=story.id,
            entity_key="character:static-future",
            entity_type="character",
            canonical_name="静态未来人物",
            source_type="agent",
            source_id=f"ai_sync:v3:entity:s{story.id}:future",
        ),
        StoryPlotThread(
            story_id=story.id,
            thread_key="thread:future-realm",
            title="陈玄突破筑基境",
            source_type="agent",
            source_id=f"ai_sync:v3:thread:c{second_chapter.id}:future",
            status="open",
        ),
    ])
    db.commit()

    chapter_one = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 1, "title": "残卷", "goal": "陈玄解决债务，避免未来长老和静态未来人物干扰"},
    )
    chapter_one_values = {item["value"] for item in chapter_one["sections"]["facts"]}
    chapter_one_threads = {item["key"] for item in chapter_one["sections"]["open_threads"]}

    assert "债务尚未还清" in chapter_one_values
    assert "债务已经还清" not in chapter_one_values
    assert "陈玄突破筑基境" not in chapter_one_values
    assert "thread:future-realm" not in chapter_one_threads
    assert all(item["key"] != "character:future-elder" for item in chapter_one["sections"]["entities"])
    assert all(item["key"] != "character:static-future" for item in chapter_one["sections"]["entities"])

    chapter_two = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 2, "title": "试探", "goal": "确认债务状态"},
    )
    debt_states = [
        item["value"]
        for item in chapter_two["sections"]["facts"]
        if item["predicate"] == "债务状态"
    ]
    assert debt_states == ["债务已经还清"]


def test_chapter_creation_pack_canonical_includes_recent_continuity_and_user_instruction():
    from services.chapter_creation_pack import render_creation_pack

    db = _session()
    story = _story(db)
    db.add_all([
        Chapter(
            story_id=story.id,
            chapter_number=2,
            title="灰市",
            novel_content="陈玄在灰市发现旧神契约的残痕。结尾他听见林月呼救。",
            memory_summary={"summary": "陈玄进入灰市", "ending_scene": "林月在巷口呼救"},
        ),
        Chapter(
            story_id=story.id,
            chapter_number=3,
            title="巷战",
            novel_content="林月交出半枚玉佩，提醒陈玄不要相信灰市牙人。",
            memory_summary={
                "summary": "林月交出玉佩",
                "ending_scene": "灰市牙人盯上陈玄",
                "chapter_handoff": {
                    "ending_location": "灰市巷口",
                    "active_conflict": "牙人正带人封住出口",
                    "active_characters": ["陈玄", "林月"],
                    "opening_must_continue": "必须先处理牙人封路，才能转场",
                },
            },
        ),
    ])
    db.commit()

    pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 4, "title": "契约", "goal": "追查旧神契约"},
        user_instruction="强化林月与旧神契约的关联",
    )
    content = render_creation_pack(pack)

    assert "上一章强制衔接" in content
    assert "正文结尾原文" in content
    assert "林月交出半枚玉佩" in content
    assert "开头必须承接：必须先处理牙人封路，才能转场" in content
    assert "前文章节" in content
    assert "陈玄取得残卷" in content
    assert "林月在巷口呼救" in content
    assert "灰市牙人盯上陈玄" in content
    assert "故事记忆" in content
    assert "陈玄持有残卷" in content
    assert "用户要求" in content
    assert "强化林月与旧神契约的关联" in content
    expected_hash = hashlib.sha256(
        json.dumps(pack["sections"], ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    receipt = db.query(AgentContextReceipt).filter(AgentContextReceipt.receipt_id == pack["receipt_id"]).one()
    assert pack["context_hash"] == expected_hash
    assert receipt.context_hash == expected_hash

    internal_pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 4, "title": "契约", "goal": "追查旧神契约"},
        user_instruction="生成本章正文创作包",
    )
    assert "生成本章正文创作包" not in render_creation_pack(internal_pack)


def test_creation_pack_ai_disables_thinking_and_retries_empty_content_once(monkeypatch):
    import services.creation_pack_ai as creation_pack_ai

    payloads: list[dict] = []
    responses = [
        {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "", "reasoning_content": "推理内容"},
            }],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 2000}},
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": '{"chapter_task":{"goal":"进入秘境"}}'},
            }],
        },
    ]

    class FakeResponse:
        def __init__(self, data):
            self._data = data
            self.text = None

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            payloads.append(json)
            return FakeResponse(responses[len(payloads) - 1])

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(creation_pack_ai.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(creation_pack_ai.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(creation_pack_ai._deepseek, "runtime_base_url", lambda: "https://example.invalid/v1")
    monkeypatch.setattr(creation_pack_ai._deepseek, "runtime_model", lambda: "deepseek-v4-flash")

    result = asyncio.run(creation_pack_ai._call_creation_pack_ai("sk-test", "系统", "用户"))

    assert result["chapter_task"]["goal"] == "进入秘境"
    assert len(payloads) == 2
    assert all(payload["thinking"] == {"type": "disabled"} for payload in payloads)


def test_creation_pack_fallback_is_not_marked_as_ai_generated(monkeypatch):
    import main as main_module

    db = _session()
    story = _story(db)

    monkeypatch.setattr(
        main_module,
        "_resolve_creation_pack_source",
        lambda *_args, **_kwargs: ({"sections": {"chapter_plan": {"title": "试探"}}}, "source-hash"),
    )

    async def render_fallback(*_args, **_kwargs):
        return "# 第2章创作包\n\n## 连续性约束\n- 承接上一章", False

    monkeypatch.setattr(main_module, "_render_creation_pack_with_ai", render_fallback)

    chapter, _chapter_info = asyncio.run(main_module._ensure_chapter_creation_pack_ai(
        db,
        story=story,
        chapter_number=2,
        owner_user_id=None,
        api_key="sk-test",
    ))

    assert chapter.creation_pack_content.startswith("# 第2章创作包")
    assert chapter.creation_pack_ai_generated is False


def test_legacy_generic_creation_pack_is_considered_stale(monkeypatch):
    import main as main_module

    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id, chapter_number=1).one()
    chapter.creation_pack_content = "# 旧版创作包\n## 章节规划\n通用检索结果"
    chapter.creation_pack_ai_generated = True
    chapter.creation_pack_source_hash = "source-hash"
    db.commit()

    monkeypatch.setattr(
        main_module,
        "_resolve_creation_pack_source",
        lambda *_args, **_kwargs: ({"sections": {}}, "source-hash"),
    )

    async def render_fresh(*_args, **_kwargs):
        return "## 本章任务\n进入\n## 剧情推进\n冲突\n## 连续性约束\n承接", True

    monkeypatch.setattr(main_module, "_render_creation_pack_with_ai", render_fresh)
    refreshed, _chapter_info = asyncio.run(main_module._ensure_chapter_creation_pack_ai(
        db,
        story=story,
        chapter_number=1,
        owner_user_id=None,
        api_key="sk-test",
    ))

    assert refreshed.creation_pack_content.startswith("## 本章任务")
    assert refreshed.creation_pack_ai_generated is True


def test_chapter_writer_keeps_immediate_previous_chapter_under_tight_budget():
    db = _session()
    story = _story(db)
    for chapter_number in range(2, 9):
        db.add(Chapter(
            story_id=story.id,
            chapter_number=chapter_number,
            title=f"推进{chapter_number}",
            novel_content=(f"第{chapter_number}章正文。" * 500) + f"第{chapter_number}章唯一结尾标记。",
            memory_summary={
                "chapter_summary": {
                    "summary": f"第{chapter_number}章摘要",
                    "ending_scene": f"第{chapter_number}章结尾场景",
                },
                "chapter_handoff": {
                    "opening_must_continue": f"承接第{chapter_number}章即时冲突",
                },
            },
            status="completed",
        ))
    db.commit()

    pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 9, "title": "继续追击", "goal": "处理上一章冲突"},
        token_budget=700,
    )

    previous = pack["sections"]["previous_chapter"]
    assert previous["chapter_number"] == 8
    assert "第8章唯一结尾标记" in previous["ending_excerpt"]
    assert previous["chapter_handoff"]["opening_must_continue"] == "承接第8章即时冲突"
    assert pack["sections"]["recent_chapters"][-1]["chapter_number"] == 7
    assert pack["context_chars"] <= 2100

    db.add(Chapter(
        story_id=story.id,
        chapter_number=9,
        title="空白占位章",
        novel_content="  \n\t",
        status="pending",
    ))
    db.commit()
    next_pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 10, "title": "继续追击", "goal": "承接最近有效正文"},
        token_budget=700,
    )
    assert next_pack["sections"]["previous_chapter"]["chapter_number"] == 8
    assert next_pack["sections"]["recent_chapters"][-1]["chapter_number"] == 7


def test_creation_pack_target_is_first_unwritten_chapter_and_rejects_future_chapters():
    import main as main_module
    from fastapi import HTTPException

    db = _session()
    story = _story(db)
    db.add_all([
        Chapter(story_id=story.id, chapter_number=2, title="第二章", novel_content="已生成正文", status="completed"),
        Chapter(story_id=story.id, chapter_number=3, title="第三章占位", novel_content=" \n\t", status="pending"),
    ])
    db.commit()

    assert main_module._next_unwritten_chapter_number(story.id, db) == 3
    with pytest.raises(HTTPException) as exc_info:
        main_module._require_current_creation_pack_chapter(story.id, 4, db)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["expected_chapter_number"] == 3


def test_creation_pack_target_does_not_skip_an_intermediate_chapter_gap():
    import main as main_module

    db = _session()
    story = _story(db)
    db.add_all([
        Chapter(
            story_id=story.id,
            chapter_number=2,
            title="第二章",
            novel_content="第二章正文",
            status="completed",
        ),
        Chapter(
            story_id=story.id,
            chapter_number=4,
            title="第四章",
            novel_content="第四章正文",
            status="completed",
        ),
    ])
    db.commit()

    assert main_module._next_unwritten_chapter_number(story.id, db) == 3


def test_chapter_context_summaries_merge_outline_and_db_chapters():
    import main as main_module

    db = _session()
    story = _story(db)
    chapter_one = db.query(Chapter).filter_by(story_id=story.id).one()
    chapter_one.creation_pack_content = "# 第1章创作包"
    chapter_one.creation_pack_version = 2
    chapter_one.creation_pack_is_manual = True
    db.commit()

    chapters, next_unwritten = main_module._chapter_context_summaries(story, db)

    assert next_unwritten == 2
    assert [item["chapter_number"] for item in chapters] == [1, 2]
    first = chapters[0]
    assert first["chapter_id"] == chapter_one.id
    assert first["title"] == "残卷"
    assert first["has_novel"] is True
    assert first["has_pack"] is True
    assert first["is_manual"] is True
    assert first["version"] == 2
    assert first["word_count"] > 0
    second = chapters[1]
    assert second["has_novel"] is False
    assert second["has_pack"] is False
    assert second["is_current"] is True
    assert second["chapter_id"] is None


def test_chapter_context_summaries_include_db_only_chapters():
    import main as main_module

    db = _session()
    story = _story(db)
    db.add(Chapter(story_id=story.id, chapter_number=7, title="大纲外章节", novel_content="", status="pending"))
    db.commit()

    chapters, _ = main_module._chapter_context_summaries(story, db)

    numbers = [item["chapter_number"] for item in chapters]
    assert 7 in numbers
    extra = next(item for item in chapters if item["chapter_number"] == 7)
    assert extra["title"] == "大纲外章节"
    assert extra["has_novel"] is False


def test_chapter_context_summaries_includes_active_refresh_task(monkeypatch):
    """进行中的创作包提取任务应在列表摘要中以 refresh_task 返回，供前端恢复轮询。"""
    import main as main_module
    from models import BackgroundTask

    db = _session()
    story = _story(db)
    task_id = f"creation_pack_{story.id}_2_running"
    db.add(BackgroundTask(
        task_id=task_id,
        task_type="chapter_creation_pack_refresh",
        story_id=story.id,
        status="running",
        metadata_json={"stage": "extracting", "message": "正在重新提取第2章创作包"},
    ))
    db.commit()

    # 避免 task_manager.get_task_status 访问生产数据库：直接返回与任务状态一致的 dict
    monkeypatch.setattr(
        main_module.task_manager,
        "get_task_status",
        lambda tid: {
            "task_id": tid,
            "task_type": "chapter_creation_pack_refresh",
            "status": "running",
            "stage": "extracting",
            "message": "正在重新提取第2章创作包",
            "metadata_json": {"stage": "extracting", "message": "正在重新提取第2章创作包"},
        },
    )

    chapters, _ = main_module._chapter_context_summaries(story, db)

    by_number = {item["chapter_number"]: item for item in chapters}
    running = by_number[2]
    assert running["refresh_task"] is not None
    assert running["refresh_task"]["task_id"] == task_id
    assert running["refresh_task"]["status"] == "running"
    # 未进行任务的其他章节摘要不应携带任务状态
    assert by_number[1]["refresh_task"] is None


def test_chapter_context_summaries_refresh_task_null_without_active_task(monkeypatch):
    """没有进行中的提取任务（含仅剩终态任务）时，摘要的 refresh_task 应为 null。"""
    import main as main_module
    from models import BackgroundTask

    db = _session()
    story = _story(db)
    db.add(BackgroundTask(
        task_id=f"creation_pack_{story.id}_2_done",
        task_type="chapter_creation_pack_refresh",
        story_id=story.id,
        status="succeeded",
        metadata_json={"stage": "succeeded", "message": "任务已完成"},
    ))
    db.commit()

    # 终态任务不应被 active 查询命中，因此不会触发 get_task_status 调用
    monkeypatch.setattr(
        main_module.task_manager,
        "get_task_status",
        lambda tid: {
            "task_id": tid,
            "task_type": "chapter_creation_pack_refresh",
            "status": "succeeded",
        },
    )

    chapters, _ = main_module._chapter_context_summaries(story, db)

    by_number = {item["chapter_number"]: item for item in chapters}
    assert by_number[2]["refresh_task"] is None


def test_update_story_chapter_context_allows_written_chapter(monkeypatch):
    import main as main_module
    from types import SimpleNamespace

    db = _session()
    story = _story(db)
    chapter_one = db.query(Chapter).filter_by(story_id=story.id).one()
    assert chapter_one.novel_content.strip()

    user = SimpleNamespace(id=1)
    monkeypatch.setattr(main_module, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main_module, "_require_story_for_user", lambda story_id, user, db: story)

    response = main_module.update_story_chapter_context(
        story_id=story.id,
        payload=SimpleNamespace(content="全新创作包内容", expected_version=1),
        request=SimpleNamespace(),
        chapter_number=1,
        db=db,
    )
    assert response["content"] == "全新创作包内容"
    assert response["is_manual"] is True
    assert response["version"] == 2


def test_background_regenerate_allows_written_chapter(monkeypatch):
    import main as main_module
    from types import SimpleNamespace

    db = _session()
    story = _story(db)
    chapter_one = db.query(Chapter).filter_by(story_id=story.id).one()
    assert chapter_one.novel_content.strip()

    captured: dict = {}

    async def fake_ensure(db, *, story, chapter_number, owner_user_id, api_key, force, expected_version):
        chapter = db.query(Chapter).filter_by(story_id=story.id, chapter_number=chapter_number).one()
        captured["called"] = True
        captured["force"] = force
        return chapter, {}

    monkeypatch.setattr(main_module, "_ensure_chapter_creation_pack_ai", fake_ensure)
    monkeypatch.setattr(main_module, "task_manager", SimpleNamespace(update_task_metadata=lambda *a, **k: None))
    monkeypatch.setattr(main_module, "SessionLocal", lambda: db)

    asyncio.run(main_module._background_regenerate_chapter_creation_pack(
        story_id_value=story.id,
        chapter_number=1,
        owner_user_id=1,
        expected_version=1,
        deepseek_api_key="test-key",
    ))
    assert captured.get("called") is True
    assert captured["force"] is True


def test_ai_sync_fact_fallback_never_reuses_static_fact_for_a_chapter():
    db = _session()
    story = _story(db)
    chapter = Chapter(
        story_id=story.id,
        chapter_number=2,
        title="第二章",
        novel_content="第二章正文",
        status="completed",
    )
    db.add(chapter)
    db.flush()
    raw_fact = {
        "stable_key": "same-fact",
        "subject_key": "character:陈玄",
        "predicate": "状态",
        "value_text": "受伤",
    }

    _merge_results(
        db,
        story,
        [{"_source_id": f"story:{story.id}:static:0", "facts": [raw_fact]}],
        include_kinds={"facts"},
    )
    _merge_results(
        db,
        story,
        [{"_source_id": f"chapter:{chapter.id}:0", "facts": [raw_fact]}],
        include_kinds={"facts"},
    )

    rows = db.query(StoryKnowledgeFact).filter_by(story_id=story.id).all()
    assert len(rows) == 2
    assert {row.source_chapter_id for row in rows} == {None, chapter.id}


def test_scoped_sync_merge_does_not_touch_other_knowledge_kinds():
    db = _session()
    story = _story(db)
    payload = [{
        "_source_id": "chapter:1:0",
        "entities": [{"entity_key": "character:scope", "canonical_name": "范围人物"}],
        "facts": [{"stable_key": "scope-fact", "subject_key": "character:scope", "predicate": "状态", "value_text": "有效"}],
        "plot_threads": [{"thread_key": "scope-thread", "title": "范围伏笔", "status": "open"}],
    }]
    counts = _merge_results(db, story, payload, include_kinds={"facts"})
    assert counts["facts"] == 1
    assert counts["entities"] == 0
    assert counts["plot_threads"] == 0
    assert db.query(StoryKnowledgeFact).filter_by(story_id=story.id).count() == 1
    assert db.query(StoryKnowledgeEntity).filter_by(story_id=story.id).count() == 0
    assert db.query(StoryPlotThread).filter_by(story_id=story.id).count() == 0


def test_chapter_writer_filters_resource_validity_before_candidate_limit():
    db = _session()
    story = _story(db)
    for index in range(80):
        db.add(StoryKnowledgeResource(
            story_id=story.id,
            resource_type="writing_rule",
            resource_key=f"future-rule:{index}",
            title=f"未来规则 {index}",
            summary="尚未生效",
            source_type="manual",
            importance=100,
            valid_from_chapter=100,
            status="active",
        ))
    db.add(StoryKnowledgeResource(
        story_id=story.id,
        resource_type="writing_rule",
        resource_key="current-rule:dialogue",
        title="旧神契约对话规则",
        summary="本章对话必须围绕旧神契约推进",
        source_type="manual",
        importance=1,
        valid_from_chapter=1,
        valid_to_chapter=10,
        status="active",
    ))
    db.commit()

    pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 5, "title": "契约", "goal": "通过对话推进旧神契约"},
    )

    resources = pack["sections"].get("resources", [])
    assert [item["key"] for item in resources] == ["current-rule:dialogue"]


def test_chapter_writer_retrieves_old_semantic_fact_beyond_latest_window():
    db = _session()
    story = _story(db)
    db.add(StoryKnowledgeFact(
        story_id=story.id,
        subject_key="world:old-god-contract",
        predicate="秘密",
        value_text="旧神契约要求以玉佩残痕作为开启凭证",
        valid_from_chapter=1,
        confidence=1,
        source_type="manual",
    ))
    db.flush()
    for index in range(260):
        db.add(StoryKnowledgeFact(
            story_id=story.id,
            subject_key=f"world:filler-{index}",
            predicate="背景",
            value_text=f"普通背景事实 {index}",
            valid_from_chapter=1,
            confidence=1,
        ))
    db.commit()

    pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 5, "title": "契约", "goal": "揭示旧神契约与玉佩残痕"},
    )
    values = {item["value"] for item in pack["sections"]["facts"]}

    assert "旧神契约要求以玉佩残痕作为开启凭证" in values


def test_chapter_writer_retrieves_low_priority_due_thread_beyond_priority_window():
    db = _session()
    story = _story(db)
    db.add(StoryPlotThread(
        story_id=story.id,
        thread_key="thread:low-priority-due",
        title="低优先级玉佩回收",
        description="本章必须让玉佩残痕产生回收",
        setup_chapter=1,
        expected_payoff_from=5,
        expected_payoff_to=5,
        priority=1,
        status="open",
    ))
    db.flush()
    for index in range(190):
        db.add(StoryPlotThread(
            story_id=story.id,
            thread_key=f"thread:background-{index}",
            title=f"高优先级背景伏笔 {index}",
            description="未来很久以后再处理",
            setup_chapter=1,
            expected_payoff_from=80,
            expected_payoff_to=90,
            priority=200,
            status="open",
        ))
    db.commit()

    pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={"chapter_number": 5, "title": "玉佩", "goal": "推进灰市交锋"},
    )
    threads = {item["key"]: item for item in pack["sections"]["open_threads"]}

    assert threads["thread:low-priority-due"]["urgency"] == "due"


def test_agent_refreshes_stale_auto_pack_but_preserves_manual_pack(monkeypatch):
    from services import agent_service
    from services.chapter_creation_pack import creation_pack_source_hash

    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id, chapter_number=1).one()
    chapter_info = {"chapter_number": 1, "title": "残卷", "goal": "取得残卷"}
    current_pack = {
        "story_id": story.id,
        "chapter_number": 1,
        "chapter_title": "残卷",
        "sections": {"chapter_plan": {"current": chapter_info}},
    }
    chapter.creation_pack_content = "# 旧自动创作包"
    chapter.creation_pack_source_hash = "old-hash"
    chapter.creation_pack_is_manual = False
    chapter.creation_pack_version = 2
    db.commit()
    monkeypatch.setattr(agent_service, "resolve_chapter_context_pack", lambda *_args, **_kwargs: current_pack)

    auto_pack = agent_service._ensure_agent_chapter_creation_pack(
        db,
        story=story,
        chapter=chapter,
        chapter_info=chapter_info,
    )
    assert auto_pack["canonical_content"] != "# 旧自动创作包"
    assert chapter.creation_pack_source_hash == creation_pack_source_hash(current_pack)
    assert chapter.creation_pack_version == 3

    chapter.creation_pack_content = "# 用户手工创作包"
    chapter.creation_pack_is_manual = True
    db.commit()
    monkeypatch.setattr(
        agent_service,
        "resolve_chapter_context_pack",
        lambda *_args, **_kwargs: pytest.fail("手工创作包不应被重新提取"),
    )
    manual_pack = agent_service._ensure_agent_chapter_creation_pack(
        db,
        story=story,
        chapter=chapter,
        chapter_info=chapter_info,
    )
    assert manual_pack["canonical_content"] == "# 用户手工创作包"


def test_agent_refresh_does_not_overwrite_manual_pack_saved_during_resolution(monkeypatch):
    from services import agent_service

    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id, chapter_number=1).one()
    chapter.creation_pack_content = "# 旧自动创作包"
    chapter.creation_pack_source_hash = "old-hash"
    chapter.creation_pack_is_manual = False
    chapter.creation_pack_version = 2
    db.commit()

    candidate_pack = {
        "story_id": story.id,
        "chapter_number": 1,
        "chapter_title": "残卷",
        "sections": {"chapter_plan": {"current": {"chapter_number": 1}}},
    }

    def save_manual_pack_during_resolution(*_args, **_kwargs):
        chapter.creation_pack_content = "# 并发保存的用户手工创作包"
        chapter.creation_pack_is_manual = True
        chapter.creation_pack_version = 3
        db.flush()
        return candidate_pack

    monkeypatch.setattr(agent_service, "resolve_chapter_context_pack", save_manual_pack_during_resolution)

    result = agent_service._ensure_agent_chapter_creation_pack(
        db,
        story=story,
        chapter=chapter,
        chapter_info={"chapter_number": 1, "title": "残卷"},
    )

    assert result["canonical_content"] == "# 并发保存的用户手工创作包"
    assert chapter.creation_pack_is_manual is True
    assert chapter.creation_pack_version == 3


def test_api_auto_refresh_does_not_overwrite_manual_pack_saved_during_resolution(monkeypatch):
    import main as main_module

    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id, chapter_number=1).one()
    chapter.creation_pack_content = "# 旧自动创作包"
    chapter.creation_pack_source_hash = "old-hash"
    chapter.creation_pack_is_manual = False
    chapter.creation_pack_version = 2
    db.commit()

    candidate_pack = {
        "story_id": story.id,
        "chapter_number": 1,
        "chapter_title": "残卷",
        "sections": {"chapter_plan": {"current": {"chapter_number": 1}}},
    }

    def save_manual_pack_during_resolution(*_args, **_kwargs):
        chapter.creation_pack_content = "# 并发保存的用户手工创作包"
        chapter.creation_pack_is_manual = True
        chapter.creation_pack_version = 3
        db.flush()
        return candidate_pack, "new-auto-hash"

    monkeypatch.setattr(main_module, "_resolve_creation_pack_source", save_manual_pack_during_resolution)

    locked_chapter, _chapter_info = main_module._ensure_chapter_creation_pack(
        db,
        story=story,
        chapter_number=1,
        owner_user_id=None,
    )

    assert locked_chapter.creation_pack_content == "# 并发保存的用户手工创作包"
    assert locked_chapter.creation_pack_is_manual is True
    assert locked_chapter.creation_pack_version == 3


def test_search_is_scoped_to_current_story():
    db = _session()
    story = _story(db, "作品甲")
    other = _story(db, "作品乙")
    db.add_all([
        StoryKnowledgeResource(
            story_id=story.id,
            resource_type="world_rule",
            resource_key="rule:spirit-stone",
            title="灵石规则",
            summary="灵石不能直接提升境界",
        ),
        StoryKnowledgeResource(
            story_id=other.id,
            resource_type="world_rule",
            resource_key="rule:other",
            title="灵石秘密",
            summary="其他作品内容",
        ),
    ])
    db.commit()

    result = search_story_knowledge(db, story_id=story.id, query="灵石")

    assert len(result["results"]) == 1
    assert result["results"][0]["key"] == "rule:spirit-stone"


def test_known_skills_receive_foundational_knowledge_tools_but_unknown_skills_fail_closed():
    from services.agent_service import skill_registry

    known_tools = skill_registry.get_tool_set(["chapter_writer"])

    assert "resolve_story_context" in known_tools
    assert "search_story_knowledge" in known_tools
    assert skill_registry.get_tool_set([]) == set()
    assert skill_registry.get_tool_set(["unknown_skill"]) == set()


def test_context_receipt_becomes_stale_after_story_mutation():
    db = _session()
    story = _story(db)

    assert validate_context_receipt(db, story_id=story.id, run_id="run-1") == (False, "context_not_resolved")
    resolve_story_context(db, story=story, task_type="framework_designer", run_id="run-1")
    assert validate_context_receipt(db, story_id=story.id, run_id="run-1") == (True, "ok")

    bump_story_knowledge_revision(db, story.id)

    assert validate_context_receipt(db, story_id=story.id, run_id="run-1") == (False, "context_stale")


def test_context_receipt_is_scoped_to_owner():
    db = _session()
    story = _story(db)
    resolve_story_context(
        db,
        story=story,
        task_type="chapter_writer",
        owner_user_id=7,
        run_id="run-owner",
    )

    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-owner",
        owner_user_id=7,
    ) == (True, "ok")
    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-owner",
        owner_user_id=8,
    ) == (False, "context_not_resolved")


def test_context_receipt_is_scoped_to_task_and_chapter():
    db = _session()
    story = _story(db)
    resolve_story_context(
        db,
        story=story,
        task_type="chapter_writer",
        chapter_number=1,
        run_id="run-task",
    )

    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-task",
        task_types=("chapter_writer",),
        chapter_number=1,
    ) == (True, "ok")
    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-task",
        task_types=("framework_designer",),
    ) == (False, "context_not_resolved")
    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-task",
        task_types=("chapter_writer",),
        chapter_number=2,
    ) == (False, "context_not_resolved")


def test_context_receipt_accepts_any_chapter_for_framework_tools():
    """框架类写工具（验证时不传章节号）接受 resolve 时带章节号的读取凭证。"""
    db = _session()
    story = _story(db)
    # Agent 规划第 21-30 章时 resolve 传了具体章节号
    resolve_story_context(
        db,
        story=story,
        task_type="framework_designer",
        chapter_number=21,
        run_id="run-framework",
    )
    # add_chapter_plan / apply_framework_ops 等框架工具验证时不传章节号
    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-framework",
        task_types=("framework_designer",),
    ) == (True, "ok")


def test_context_receipt_accepts_unbound_receipt_for_chapter_tools():
    """正文写工具（带章节号验证）接受 resolve 时未绑定章节号的读取凭证。"""
    db = _session()
    story = _story(db)
    resolve_story_context(
        db,
        story=story,
        task_type="chapter_writer",
        run_id="run-writer-unbound",
    )
    assert validate_context_receipt(
        db,
        story_id=story.id,
        run_id="run-writer-unbound",
        task_types=("chapter_writer",),
        chapter_number=3,
    ) == (True, "ok")


def test_story_and_chapter_writes_advance_revision_automatically():
    db = _session()
    story = _story(db)
    initial_revision = story.knowledge_revision

    story.description = "更新后的作品简介"
    db.commit()
    assert story.knowledge_revision == initial_revision + 1

    chapter = db.query(Chapter).filter_by(story_id=story.id).one()
    chapter.novel_content = "新的章节正文"
    db.commit()
    assert story.knowledge_revision == initial_revision + 2

    chapter.manga_storyboard_json = {"scenes": ["新的场景"]}
    db.commit()
    assert story.knowledge_revision == initial_revision + 3


def test_agent_revision_guard_rolls_back_write_after_context_becomes_stale(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'revision-guard.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id).one()
    guarded_revision = story.knowledge_revision

    concurrent_db = factory()
    concurrent_story = concurrent_db.get(Story, story.id)
    concurrent_story.description = "并发更新后的设定"
    concurrent_db.commit()
    concurrent_db.close()

    token = set_agent_knowledge_revision_guard(story.id, guarded_revision)
    try:
        chapter.novel_content = "基于过期上下文的正文"
        with pytest.raises(StaleKnowledgeContextError, match="重新读取"):
            db.commit()
        db.rollback()
    finally:
        reset_agent_knowledge_revision_guard(token)

    db.refresh(chapter)
    assert chapter.novel_content != "基于过期上下文的正文"


def test_tool_registry_requires_receipt_and_bumps_only_after_real_write(monkeypatch):
    from services import agent_service

    closed_sessions = []
    handler_calls = []

    class FakeSession:
        def close(self):
            closed_sessions.append(True)

    async def fake_handler(**kwargs):
        handler_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(agent_service, "SessionLocal", FakeSession)
    monkeypatch.setitem(agent_service.tool_registry._tools["update_story_info"], "handler", fake_handler)

    context = agent_service.AgentRunContext(
        story_id=31,
        api_key=None,
        pending_changes=agent_service.PendingChangesTracker(),
        pending_change_key=agent_service.AgentPendingChangeKey(user_id=7, story_id=31, conversation_id=9),
        workflow_type="novel",
        enabled_skills=None,
        run_id="run-gate",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        monkeypatch.setattr(agent_service, "validate_context_receipt", lambda *_args, **_kwargs: (False, "context_not_resolved"))
        rejected = json.loads(asyncio.run(agent_service.tool_registry.execute("update_story_info", {"story_id": 31})))
        assert rejected["context_required"] is True
        assert handler_calls == []

        monkeypatch.setattr(agent_service, "validate_context_receipt", lambda *_args, **_kwargs: (True, "ok"))
        accepted = json.loads(asyncio.run(agent_service.tool_registry.execute("update_story_info", {"story_id": 31})))
        assert accepted["ok"] is True
        assert handler_calls == [{"story_id": 31}]
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert len(closed_sessions) == 2


def test_tool_registry_restores_pending_changes_when_stale_error_is_swallowed(monkeypatch):
    from services import agent_service

    class FakeSession:
        def get(self, _model, _story_id):
            return type("StoryRecord", (), {"knowledge_revision": 8})()

        def close(self):
            pass

    tracker = agent_service.PendingChangesTracker()

    async def fake_handler(**_kwargs):
        tracker.record(agent_service.PendingChange(
            type="chapter",
            record_id=5,
            display_name="第2章",
            field="novel_content",
            old_value="旧正文",
            new_value="未提交正文",
        ))
        return {"error": "工具内部捕获了提交异常"}

    monkeypatch.setattr(agent_service, "SessionLocal", FakeSession)
    monkeypatch.setattr(agent_service, "validate_context_receipt", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(agent_service, "agent_knowledge_revision_guard_is_stale", lambda: True)
    monkeypatch.setitem(agent_service.tool_registry._tools["update_story_info"], "handler", fake_handler)
    context = agent_service.AgentRunContext(
        story_id=31,
        api_key=None,
        pending_changes=tracker,
        workflow_type="novel",
        enabled_skills=None,
        run_id="run-stale-swallowed",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = json.loads(asyncio.run(agent_service.tool_registry.execute(
            "update_story_info",
            {"story_id": 31},
        )))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["context_required"] is True
    assert result["reason"] == "context_stale"
    assert tracker.has_changes() is False


def test_tool_registry_dry_run_does_not_bump_revision(monkeypatch):
    from services import agent_service

    class FakeSession:
        def close(self):
            pass

    async def fake_handler(**_kwargs):
        return {"ok": True, "dry_run": True}

    monkeypatch.setattr(agent_service, "SessionLocal", FakeSession)
    monkeypatch.setattr(agent_service, "validate_context_receipt", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setitem(agent_service.tool_registry._tools["apply_framework_ops"], "handler", fake_handler)
    context = agent_service.AgentRunContext(
        story_id=31,
        api_key=None,
        pending_changes=agent_service.PendingChangesTracker(),
        workflow_type="novel",
        enabled_skills=None,
        run_id="run-dry",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = json.loads(asyncio.run(agent_service.tool_registry.execute(
            "apply_framework_ops",
            {"story_id": 31, "operations": [], "dry_run": True},
        )))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["dry_run"] is True


def test_batch_mutation_resolves_every_target_chapter():
    from services import agent_service

    chapters = {
        11: type("ChapterRecord", (), {"story_id": 31, "chapter_number": 2})(),
        12: type("ChapterRecord", (), {"story_id": 31, "chapter_number": 5})(),
        13: type("ChapterRecord", (), {"story_id": 99, "chapter_number": 8})(),
    }

    class FakeSession:
        def get(self, _model, chapter_id):
            return chapters.get(chapter_id)

    context = agent_service.AgentRunContext(
        story_id=31,
        api_key=None,
        pending_changes=agent_service.PendingChangesTracker(),
        workflow_type="novel",
        run_id="run-batch",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        numbers = agent_service._mutation_target_chapter_numbers(
            FakeSession(),
            "batch_update_chapters",
            {"chapters": [{"chapter_id": 11}, {"chapter_id": 12}, {"chapter_id": 13}]},
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert numbers == (2, 5)


def test_create_chapter_receipt_targets_the_next_chapter_number():
    from services import agent_service

    db = _session()
    story = _story(db)
    context = agent_service.AgentRunContext(
        story_id=story.id,
        api_key=None,
        pending_changes=agent_service.PendingChangesTracker(),
        workflow_type="novel",
        run_id="run-create-chapter",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        numbers = agent_service._mutation_target_chapter_numbers(
            db,
            "create_chapter",
            {"story_id": story.id, "title": "第二章"},
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert numbers == (2,)


def test_manga_and_video_workflows_can_read_story_knowledge():
    from services import agent_service

    for workflow_type in ("manga", "video"):
        allowed = agent_service.tool_registry._effective_tool_names(
            workflow_type,
            None,
        )
        assert "resolve_story_context" in allowed
        assert "search_story_knowledge" in allowed


def test_framework_mutation_uses_story_level_receipt(monkeypatch):
    from services import agent_service

    validated_chapters = []

    class FakeSession:
        def close(self):
            pass

    async def fake_handler(**_kwargs):
        return {"ok": True}

    def fake_validate(*_args, **kwargs):
        validated_chapters.append(kwargs.get("chapter_number"))
        return True, "ok"

    monkeypatch.setattr(agent_service, "SessionLocal", FakeSession)
    monkeypatch.setattr(agent_service, "validate_context_receipt", fake_validate)
    monkeypatch.setitem(agent_service.tool_registry._tools["add_chapter_plan"], "handler", fake_handler)
    context = agent_service.AgentRunContext(
        story_id=31,
        api_key=None,
        pending_changes=agent_service.PendingChangesTracker(),
        workflow_type="novel",
        enabled_skills=None,
        run_id="run-framework",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = json.loads(asyncio.run(agent_service.tool_registry.execute(
            "add_chapter_plan",
            {"story_id": 31, "chapter": {"chapter_number": 2, "title": "第二章"}},
        )))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert validated_chapters == [None]


def test_manual_knowledge_crud_updates_revision_and_agent_context():
    db = _session()
    story = _story(db)
    initial_revision = story.knowledge_revision

    resource = create_story_knowledge_item(
        db,
        story=story,
        kind="resource",
        payload={
            "resource_type": "world_rule",
            "resource_key": "rule:no-resurrection",
            "title": "死亡不可逆",
            "content_text": "世界中不存在无代价复活。",
            "importance": 95,
        },
    )
    entity = create_story_knowledge_item(
        db,
        story=story,
        kind="entity",
        payload={
            "entity_type": "location",
            "entity_key": "location:gray-market",
            "canonical_name": "灰市",
            "aliases_json": ["地下集市"],
        },
    )
    fact = create_story_knowledge_item(
        db,
        story=story,
        kind="fact",
        payload={
            "subject_key": "character:chen-xuan",
            "predicate": "location",
            "object_key": "location:gray-market",
            "value_text": "陈玄已进入灰市",
            "valid_from_chapter": 2,
        },
    )
    thread = create_story_knowledge_item(
        db,
        story=story,
        kind="plot_thread",
        payload={
            "thread_type": "mystery",
            "thread_key": "mystery:gray-market-owner",
            "title": "灰市主人身份",
            "setup_chapter": 2,
            "expected_payoff_from": 12,
            "expected_payoff_to": 18,
        },
    )

    listed = list_story_knowledge(db, story=story)
    revision_after_sync = listed["knowledge_revision"]
    assert revision_after_sync == initial_revision + 5
    assert any(item["id"] == resource["id"] for item in listed["resources"])
    assert any(item["id"] == entity["id"] for item in listed["entities"])
    assert any(item["id"] == fact["id"] for item in listed["facts"])
    assert any(item["id"] == thread["id"] for item in listed["plot_threads"])

    updated = update_story_knowledge_item(
        db,
        story=story,
        kind="plot_thread",
        item_id=thread["id"],
        payload={"status": "resolved", "actual_payoff_chapter": 15, "expected_version": thread["version"]},
    )
    assert updated["status"] == "resolved"
    assert updated["version"] == 2
    assert story.knowledge_revision == revision_after_sync + 1

    context = resolve_story_context(db, story=story, task_type="chapter_writer", chapter_number=3)
    assert any(item["name"] == "灰市" for item in context["sections"]["entities"])
    assert any(item["predicate"] == "location" for item in context["sections"]["facts"])
    assert all(item["key"] != "mystery:gray-market-owner" for item in context["sections"]["open_threads"])

    delete_story_knowledge_item(
        db,
        story=story,
        kind="resource",
        item_id=resource["id"],
        expected_version=resource["version"],
    )
    assert all(item["id"] != resource["id"] for item in list_story_knowledge(db, story=story)["resources"])
    assert story.knowledge_revision == revision_after_sync + 2


def test_story_knowledge_categories_defaults_crud_and_delete_guards():
    db = _session()
    story = _story(db)

    listed = list_story_knowledge(db, story=story)
    fact_categories = [item for item in listed["categories"] if item["knowledge_kind"] == "fact"]
    thread_categories = [item for item in listed["categories"] if item["knowledge_kind"] == "plot_thread"]
    assert [item["name"] for item in fact_categories][:3] == ["基础事实", "人物关系", "世界规则"]
    assert [item["name"] for item in thread_categories][:3] == ["主要伏笔", "情感线索", "世界谜团"]
    assert listed["story_bible"]["creative_brief"]["core_hook"] == "残卷指向失落文明"
    assert listed["counts"]["fact"] >= 1

    category = create_story_knowledge_category(
        db,
        story=story,
        knowledge_kind="fact",
        payload={"name": "长期设定", "color": "#0f766e", "sort_order": 40},
    )
    renamed = update_story_knowledge_category(
        db,
        story=story,
        category_id=category["id"],
        payload={"name": "长期事实", "expected_version": category["version"]},
    )
    assert renamed["name"] == "长期事实"
    assert renamed["version"] == category["version"] + 1

    fact = create_story_knowledge_item(
        db,
        story=story,
        kind="fact",
        payload={"category_id": renamed["id"], "value_text": "灰市禁止公开交易残卷"},
    )
    assert fact["subject_key"] == "story"
    assert fact["predicate"] == "note"
    assert fact["category_name"] == "长期事实"

    with pytest.raises(StoryKnowledgeConflictError, match="引用"):
        delete_story_knowledge_category(
            db,
            story=story,
            category_id=renamed["id"],
            expected_version=renamed["version"],
        )

    extra = create_story_knowledge_category(
        db,
        story=story,
        knowledge_kind="plot_thread",
        payload={"name": "临时线索"},
    )
    delete_story_knowledge_category(
        db,
        story=story,
        category_id=extra["id"],
        expected_version=extra["version"],
    )
    remaining_threads = (
        db.query(StoryKnowledgeCategory)
        .filter_by(story_id=story.id, knowledge_kind="plot_thread")
        .all()
    )
    for category_row in remaining_threads[1:]:
        delete_story_knowledge_category(
            db,
            story=story,
            category_id=category_row.id,
            expected_version=category_row.version,
        )
    last = (
        db.query(StoryKnowledgeCategory)
        .filter_by(story_id=story.id, knowledge_kind="plot_thread")
        .one()
    )
    with pytest.raises(StoryKnowledgeConflictError, match="最后一个"):
        delete_story_knowledge_category(
            db,
            story=story,
            category_id=last.id,
            expected_version=last.version,
        )


def test_manual_friendly_defaults_and_general_resources_reach_agent_context():
    db = _session()
    story = _story(db)

    resource = create_story_knowledge_item(
        db,
        story=story,
        kind="resource",
        payload={"title": "普通资料", "content_text": "灰市只在雨夜开放。"},
    )
    entity = create_story_knowledge_item(
        db,
        story=story,
        kind="entity",
        payload={"canonical_name": "雨夜灰市"},
    )
    thread = create_story_knowledge_item(
        db,
        story=story,
        kind="plot_thread",
        payload={"title": "灰市入口为何变化"},
    )

    assert resource["resource_type"] == "manual_note"
    assert resource["resource_key"].startswith("manual:")
    assert entity["entity_type"] == "note"
    assert entity["entity_key"].startswith("manual:")
    assert thread["thread_type"] == "foreshadow"
    assert thread["thread_key"].startswith("manual:")
    assert thread["category_id"] is not None

    context = resolve_story_context(db, story=story, task_type="chapter_writer", chapter_number=2)
    assert any(item["title"] == "普通资料" for item in context["sections"].get("resources", []))


def test_story_bible_story_state_projects_into_database_knowledge_idempotently():
    db = _session()
    story = _story(db)
    story.story_bible = {
        "creative_brief": {"core_hook": "残卷指向失落文明"},
        "story_state": {
            "continuity_facts": ["林月知道残卷真名"],
            "open_loops": [{"title": "林月为何隐瞒真名", "description": "她没有解释残卷来源"}],
        },
    }
    db.commit()

    assert sync_story_knowledge_from_legacy(db, story=story) is True
    fact = db.query(StoryKnowledgeFact).filter_by(story_id=story.id, source_type="story_bible").one()
    thread = db.query(StoryPlotThread).filter_by(story_id=story.id, source_type="story_bible").one()
    assert fact.value_text == "林月知道残卷真名"
    assert fact.category_id is not None
    assert thread.title == "林月为何隐瞒真名"
    assert thread.category_id is not None

    revision_after_sync = story.knowledge_revision
    assert sync_story_knowledge_from_legacy(db, story=story) is False
    assert story.knowledge_revision == revision_after_sync

    story.story_bible = {"story_state": {"continuity_facts": [], "open_loops": []}}
    db.commit()
    assert sync_story_knowledge_from_legacy(db, story=story) is True
    db.refresh(fact)
    db.refresh(thread)
    assert fact.status == "archived"
    assert thread.status == "archived"


def test_legacy_knowledge_sync_is_idempotent_and_preserves_manual_edits():
    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id).one()

    revision_before_sync = story.knowledge_revision
    assert sync_story_knowledge_from_legacy(
        db,
        story=story,
        source_chapter_id=chapter.id,
    ) is True
    assert story.knowledge_revision == revision_before_sync + 1

    entity = db.query(StoryKnowledgeEntity).filter_by(
        story_id=story.id,
        source_type="legacy_projection",
    ).one()
    fact = db.query(StoryKnowledgeFact).filter_by(
        story_id=story.id,
        source_type="story_memory",
    ).one()
    thread = db.query(StoryPlotThread).filter_by(
        story_id=story.id,
        source_type="story_memory",
    ).one()
    assert entity.canonical_name == "陈玄"
    assert fact.value_text == "陈玄持有残卷"
    assert fact.source_chapter_id == chapter.id
    assert thread.title == "残卷来源未知"
    assert thread.status == "open"

    revision_after_sync = story.knowledge_revision
    assert sync_story_knowledge_from_legacy(
        db,
        story=story,
        source_chapter_id=chapter.id,
    ) is False
    assert story.knowledge_revision == revision_after_sync

    updated = update_story_knowledge_item(
        db,
        story=story,
        kind="entity",
        item_id=entity.id,
        payload={
            "canonical_name": "陈玄（用户设定）",
            "profile_json": {"role": "主角", "note": "以此为准"},
            "expected_version": entity.version,
        },
    )
    assert updated["source_type"] == "manual"

    story.characters = [{"name": "陈玄", "role": "主角", "motivation": "新的旧字段内容"}]
    db.commit()
    revision_before_manual_guard = story.knowledge_revision
    assert sync_story_knowledge_from_legacy(db, story=story) is False
    db.refresh(entity)
    assert entity.canonical_name == "陈玄（用户设定）"
    assert entity.profile_json == {"role": "主角", "note": "以此为准"}
    assert story.knowledge_revision == revision_before_manual_guard

    story.story_memory = {
        "continuity_facts": ["陈玄持有残卷"],
        "open_loops": [],
        "resolved_loops": ["残卷来源未知"],
    }
    db.commit()
    assert sync_story_knowledge_from_legacy(
        db,
        story=story,
        source_chapter_id=chapter.id,
    ) is True
    db.refresh(thread)
    assert thread.status == "resolved"
    assert thread.actual_payoff_chapter == chapter.chapter_number

    story.story_memory = {"continuity_facts": [], "open_loops": [], "resolved_loops": []}
    db.commit()
    assert sync_story_knowledge_from_legacy(db, story=story) is True
    db.refresh(fact)
    db.refresh(thread)
    assert fact.status == "archived"
    assert thread.status == "archived"


def test_legacy_sync_archives_removed_character_projection():
    db = _session()
    story = _story(db)
    story.characters = [
        {"name": "陈玄", "role": "主角"},
        {"name": "林月", "role": "配角"},
    ]
    db.commit()
    assert sync_story_knowledge_from_legacy(db, story=story) is True
    lin_yue = db.query(StoryKnowledgeEntity).filter_by(
        story_id=story.id,
        canonical_name="林月",
    ).one()

    story.characters = [{"name": "陈玄", "role": "主角"}]
    db.commit()
    context = resolve_story_context(db, story=story, task_type="chapter_writer", chapter_number=2)
    db.refresh(lin_yue)
    assert lin_yue.status == "archived"
    assert all(item["name"] != "林月" for item in context["sections"]["entities"])


def test_chapter_context_pack_prioritizes_task_entities_facts_and_due_threads():
    db = _session()
    story = _story(db)
    db.add_all([
        StoryKnowledgeEntity(
            story_id=story.id,
            entity_key="character:global-master",
            entity_type="character",
            canonical_name="远方宗主",
            importance=99,
        ),
        StoryKnowledgeEntity(
            story_id=story.id,
            entity_key="character:lin-yue",
            entity_type="character",
            canonical_name="林月",
            aliases_json=["月姐"],
            profile_json={"location": "灰市", "goal": "追查玉佩"},
            importance=10,
        ),
        StoryKnowledgeEntity(
            story_id=story.id,
            entity_key="character:market-dealer",
            entity_type="character",
            canonical_name="线人甲",
            importance=5,
        ),
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:lin-yue",
            predicate="持有",
            object_key="item:jade",
            value_text="林月持有裂纹玉佩",
            valid_from_chapter=2,
            confidence=1,
        ),
        StoryKnowledgeFact(
            story_id=story.id,
            subject_key="character:lin-yue",
            predicate="交易",
            object_key="character:market-dealer",
            value_text="林月向线人甲购买玉佩线索",
            valid_from_chapter=5,
            confidence=1,
        ),
        StoryPlotThread(
            story_id=story.id,
            thread_key="thread:jade-origin",
            title="玉佩来历",
            description="林月需要查明玉佩来历",
            setup_chapter=2,
            expected_payoff_from=5,
            expected_payoff_to=5,
            related_entity_keys=["character:lin-yue"],
            priority=20,
            status="open",
        ),
    ])
    db.commit()

    pack = resolve_chapter_context_pack(
        db,
        story=story,
        chapter_info={
            "chapter_number": 5,
            "title": "林月在灰市追查玉佩",
            "goal": "查明玉佩来历",
            "conflict": "林月被灰市掮客阻拦",
        },
    )

    assert pack["sections"]["entities"][0]["key"] == "character:lin-yue"
    selected_entity_keys = {item["key"] for item in pack["sections"]["entities"]}
    assert "character:market-dealer" in selected_entity_keys
    assert "character:global-master" not in selected_entity_keys
    assert pack["sections"]["facts"][0]["subject"] == "character:lin-yue"
    assert pack["sections"]["facts"][0]["subject_name"] == "林月"
    assert any(item.get("object_name") == "线人甲" for item in pack["sections"]["facts"])
    assert pack["sections"]["open_threads"][0]["key"] == "thread:jade-origin"
    assert pack["sections"]["open_threads"][0]["urgency"] == "due"
    assert pack["sections"]["open_threads"][0]["related_entity_names"] == ["林月"]
    assert pack["context_hash"]
    assert pack["retrieval"]["selected_counts"]["facts"] >= 1

    runtime_context = apply_chapter_context_pack({"characters": story.characters}, pack)
    assert runtime_context["chapter_context_pack"]["receipt_id"] == pack["receipt_id"]
    assert runtime_context["knowledge_entities"][0]["key"] == "character:lin-yue"
    assert {item["value"] for item in runtime_context["knowledge_facts"]} >= {
        "林月持有裂纹玉佩",
        "林月向线人甲购买玉佩线索",
    }
    assert runtime_context["open_threads"][0]["urgency"] == "due"


def test_chapter_context_guard_rejects_stale_generated_content():
    from fastapi import HTTPException
    from main import _commit_with_chapter_context_guard

    db = _session()
    story = _story(db)
    chapter = db.query(Chapter).filter_by(story_id=story.id).one()
    original_content = chapter.novel_content
    expected_revision = story.knowledge_revision
    bump_story_knowledge_revision(db, story.id)

    chapter.novel_content = "这段正文基于已经过期的作品设定"
    with pytest.raises(HTTPException) as exc_info:
        _commit_with_chapter_context_guard(
            db,
            story_id=story.id,
            story_context={
                "chapter_context_pack": {
                    "knowledge_revision": expected_revision,
                    "context_hash": "stale-context",
                },
            },
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "knowledge_revision_conflict"
    db.refresh(chapter)
    assert chapter.novel_content == original_content


def test_chapter_context_guard_allows_new_chapter_flush_inside_guard():
    from main import _commit_with_chapter_context_guard

    db = _session()
    story = _story(db)
    expected_revision = story.knowledge_revision
    chapter = Chapter(
        story_id=story.id,
        chapter_number=2,
        title="试探",
        novel_content="陈玄带着残卷进入灰市。",
        status="completed",
    )
    db.add(chapter)

    def prepare() -> None:
        db.flush()

    _commit_with_chapter_context_guard(
        db,
        story_id=story.id,
        story_context={
            "chapter_context_pack": {
                "knowledge_revision": expected_revision,
                "context_hash": "fresh-context",
            },
        },
        prepare=prepare,
    )

    assert chapter.id is not None
    assert db.query(Chapter).filter_by(story_id=story.id, chapter_number=2).one().novel_content
    db.refresh(story)
    assert story.knowledge_revision == expected_revision + 1


def test_chapter_context_guard_rolls_back_when_prepare_fails():
    from main import _commit_with_chapter_context_guard

    db = _session()
    story = _story(db)
    expected_revision = story.knowledge_revision
    chapter = Chapter(
        story_id=story.id,
        chapter_number=2,
        title="不会保存的章节",
        novel_content="临时正文",
        status="completed",
    )
    db.add(chapter)

    def prepare() -> None:
        db.flush()
        raise RuntimeError("模拟写入准备失败")

    with pytest.raises(RuntimeError, match="模拟写入准备失败"):
        _commit_with_chapter_context_guard(
            db,
            story_id=story.id,
            story_context={
                "chapter_context_pack": {
                    "knowledge_revision": expected_revision,
                    "context_hash": "fresh-context",
                },
            },
            prepare=prepare,
        )

    assert db.query(Chapter).filter_by(story_id=story.id, chapter_number=2).one_or_none() is None
    db.refresh(story)
    assert story.knowledge_revision == expected_revision


def test_manual_knowledge_update_rejects_stale_version():
    db = _session()
    story = _story(db)
    resource = create_story_knowledge_item(
        db,
        story=story,
        kind="resource",
        payload={"resource_type": "world_rule", "resource_key": "rule:cost", "title": "力量代价"},
    )
    second_db = sessionmaker(bind=db.get_bind(), expire_on_commit=False)()
    second_story = second_db.get(Story, story.id)
    second_db.get(StoryKnowledgeResource, resource["id"])

    updated = update_story_knowledge_item(
        db,
        story=story,
        kind="resource",
        item_id=resource["id"],
        payload={"summary": "第一次编辑", "expected_version": resource["version"]},
    )
    assert updated["version"] == resource["version"] + 1

    with pytest.raises(StoryKnowledgeConflictError, match="其他页面"):
        update_story_knowledge_item(
            second_db,
            story=second_story,
            kind="resource",
            item_id=resource["id"],
            payload={"summary": "过期编辑", "expected_version": resource["version"]},
        )
    with pytest.raises(StoryKnowledgeConflictError, match="其他页面"):
        delete_story_knowledge_item(
            second_db,
            story=second_story,
            kind="resource",
            item_id=resource["id"],
            expected_version=resource["version"],
        )
    second_db.close()


def test_story_knowledge_migration_adds_source_columns_idempotently():
    import database

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE story_knowledge_entities "
            "(id INTEGER PRIMARY KEY, story_id INTEGER, entity_key VARCHAR(160))"
        ))
        conn.execute(text(
            "CREATE TABLE story_knowledge_facts "
            "(id INTEGER PRIMARY KEY, story_id INTEGER, source_type VARCHAR(30))"
        ))
        conn.execute(text(
            "CREATE TABLE story_plot_threads "
            "(id INTEGER PRIMARY KEY, story_id INTEGER, thread_key VARCHAR(160))"
        ))

    database._migrate_story_knowledge_tables(engine)
    database._migrate_story_knowledge_tables(engine)

    inspector = inspect(engine)
    assert "story_knowledge_categories" in inspector.get_table_names()
    assert "knowledge_revision" in {column["name"] for column in inspector.get_columns("stories")}
    assert {"source_type", "source_id", "version"}.issubset(
        {column["name"] for column in inspector.get_columns("story_knowledge_entities")}
    )
    assert {"source_id", "version", "category_id"}.issubset(
        {column["name"] for column in inspector.get_columns("story_knowledge_facts")}
    )
    assert {"source_type", "source_id", "version", "category_id"}.issubset(
        {column["name"] for column in inspector.get_columns("story_plot_threads")}
    )


def test_manual_knowledge_rejects_invalid_ranges_and_cross_story_updates():
    db = _session()
    story = _story(db, "作品甲")
    other = _story(db, "作品乙")
    item = create_story_knowledge_item(
        db,
        story=story,
        kind="fact",
        payload={"subject_key": "character:a", "predicate": "knows", "valid_from_chapter": 3},
    )

    with pytest.raises(ValueError, match="valid_from_chapter"):
        update_story_knowledge_item(
            db,
            story=story,
            kind="fact",
            item_id=item["id"],
            payload={"valid_to_chapter": 2, "expected_version": item["version"]},
        )
    db.rollback()

    with pytest.raises(LookupError, match="未找到"):
        update_story_knowledge_item(
            db,
            story=other,
            kind="fact",
            item_id=item["id"],
            payload={"value_text": "越权修改"},
        )


def test_projected_knowledge_must_be_edited_before_delete():
    db = _session()
    story = _story(db)
    sync_story_knowledge_from_legacy(db, story=story)
    projected = db.query(StoryKnowledgeFact).filter_by(
        story_id=story.id,
        source_type="story_memory",
    ).first()

    with pytest.raises(StoryKnowledgeConflictError, match="先编辑"):
        delete_story_knowledge_item(
            db,
            story=story,
            kind="fact",
            item_id=projected.id,
            expected_version=projected.version,
        )


def test_dirty_story_memory_sync_advances_revision_once():
    db = _session()
    story = _story(db)
    sync_story_knowledge_from_legacy(db, story=story)
    db.refresh(story)
    initial_revision = story.knowledge_revision

    story.story_memory = {
        **story.story_memory,
        "continuity_facts": ["陈玄持有残卷", "陈玄已经进入灰市"],
    }
    assert sync_story_knowledge_from_legacy(db, story=story, commit=False) is True
    db.commit()
    db.refresh(story)

    assert story.knowledge_revision == initial_revision + 1


def test_category_delete_advances_revision_once():
    db = _session()
    story = _story(db)
    categories = list_story_knowledge(db, story=story)["categories"]
    removable = next(
        item for item in categories
        if item["knowledge_kind"] == "fact" and item["name"] == "人物关系"
    )
    db.refresh(story)
    initial_revision = story.knowledge_revision

    delete_story_knowledge_category(
        db,
        story=story,
        category_id=removable["id"],
        expected_version=removable["version"],
    )
    db.refresh(story)

    assert story.knowledge_revision == initial_revision + 1


def test_manga_storyboard_mutations_require_chapter_context_receipt():
    from services import agent_service

    tool_names = {
        "update_manga_storyboard_scene",
        "batch_update_manga_storyboard_scenes",
        "replace_manga_storyboard",
    }
    assert tool_names.issubset(agent_service._STORY_KNOWLEDGE_MUTATION_TOOLS)
    assert all(
        agent_service._STORY_KNOWLEDGE_CONTEXT_PROFILES[name] == ("chapter_writer",)
        for name in tool_names
    )
