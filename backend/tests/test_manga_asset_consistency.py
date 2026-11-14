import io
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import main
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from models import Base, MangaAsset, MangaAssetBinding
from services import image2


def test_scene_reference_selection_respects_roles_required_and_style(tmp_path: Path):
    character = tmp_path / "character.png"
    scene = tmp_path / "scene.png"
    prop = tmp_path / "prop.png"
    style = tmp_path / "style.png"
    for path in (character, scene, prop, style):
        path.write_bytes(b"test")

    entries = [
        {"path": scene, "label": "王宫大厅", "kind": "scene", "priority": 0, "is_required": False},
        {"path": character, "label": "林秋", "kind": "character", "priority": 0, "is_required": False},
        {"path": prop, "label": "银色怀表", "kind": "prop", "priority": 10, "is_required": True},
        {"path": style, "label": "水墨风格", "kind": "style", "priority": 0, "is_required": False},
    ]

    selected = main._select_ref_image_paths_for_scene("林秋站在雨夜街道", entries)

    assert [(path.name, label, role) for path, label, role in selected] == [
        ("style.png", "水墨风格", "style"),
        ("character.png", "林秋", "character"),
        ("prop.png", "银色怀表", "prop"),
    ]


def test_scene_reference_selection_matches_parenthetical_alias(tmp_path: Path):
    character = tmp_path / "character.png"
    character.write_bytes(b"test")

    selected = main._select_ref_image_paths_for_scene(
        "陈玄走进地下擂台",
        [{"path": character, "label": "陈玄（原青玄仙尊）", "kind": "character"}],
    )

    assert [(label, role) for _, label, role in selected] == [("陈玄（原青玄仙尊）", "character")]


def test_character_profiles_are_removed_when_page_has_character_asset():
    profiles = "角色名：陈玄\n三视图特征：大量人物设定"

    assert main._character_profiles_for_page(profiles, "陈玄站在门口", ["陈玄"], ["character"]) == ""
    assert main._character_profiles_for_page(profiles, "陈玄站在门口", ["旧宅"], ["scene"]) == profiles


def test_multi_character_page_keeps_profiles_when_one_reference_is_missing():
    profiles = "角色名：林秋\n外貌：黑发\n角色名：顾川\n外貌：银发"

    result = main._character_profiles_for_page(
        profiles,
        "林秋与顾川在走廊会面",
        ["林秋"],
        ["character"],
    )

    assert result == profiles


def test_implicit_style_reference_uses_only_highest_priority(tmp_path: Path):
    low = tmp_path / "low.png"
    high = tmp_path / "high.png"
    low.write_bytes(b"low")
    high.write_bytes(b"high")

    selected = main._select_ref_image_paths_for_scene(
        "无角色的空镜",
        [
            {"path": low, "kind": "style", "label": "低优先级", "priority": 1},
            {"path": high, "kind": "style_reference", "label": "高优先级", "priority": 10},
        ],
    )

    assert selected == [(high, "高优先级", "style")]


def test_explicit_style_reference_removes_other_bound_styles(tmp_path: Path):
    style = tmp_path / "old-style.png"
    character = tmp_path / "character.png"
    style.write_bytes(b"style")
    character.write_bytes(b"character")

    entries = main._effective_page_ref_entries(
        [
            {"path": style, "kind": "style", "label": "旧风格"},
            {"path": character, "kind": "character", "label": "陈玄"},
        ],
        str(tmp_path / "selected-style.png"),
    )

    assert [(entry["kind"], entry["label"]) for entry in entries] == [("character", "陈玄")]


def test_auto_asset_analysis_fingerprint_changes_with_chapter_content():
    first = main._manga_asset_analysis_fingerprint("第一版正文", "角色设定", [{"name": "陈玄"}])
    same = main._manga_asset_analysis_fingerprint("第一版正文", "角色设定", [{"name": "陈玄"}])
    changed = main._manga_asset_analysis_fingerprint("第二版正文", "角色设定", [{"name": "陈玄"}])
    character_only = main._manga_asset_analysis_fingerprint(
        "第一版正文",
        "角色设定",
        [{"name": "陈玄"}],
        {"character_reference"},
    )

    assert first == same
    assert first != changed
    assert first != character_only


def test_auto_asset_options_default_to_all_types_and_support_single_selection():
    enabled, all_types = main._normalize_auto_manga_asset_options()
    character_only, selected_types = main._normalize_auto_manga_asset_options(True, ["character"])

    assert enabled is True
    assert all_types == {"character_reference", "scene_reference", "prop_reference"}
    assert character_only is True
    assert selected_types == {"character_reference"}


def test_auto_asset_options_can_disable_preflight_or_use_empty_selection():
    disabled, disabled_types = main._normalize_auto_manga_asset_options(False, ["character", "scene"])
    empty_enabled, empty_types = main._normalize_auto_manga_asset_options(True, [])

    assert disabled is False
    assert disabled_types == {"character_reference", "scene_reference"}
    assert empty_enabled is False
    assert empty_types == set()


def test_auto_asset_options_reject_unknown_types():
    with pytest.raises(main.HTTPException) as exc_info:
        main._normalize_auto_manga_asset_options(True, ["character", "vehicle"])

    assert exc_info.value.status_code == 422


def test_auto_asset_suggestions_are_filtered_before_planning():
    suggestions = [
        {"asset_type": "character_reference", "name": "陈玄", "prompt": "角色"},
        {"asset_type": "scene_reference", "name": "擂台", "prompt": "场景"},
        {"asset_type": "prop_reference", "name": "信封", "prompt": "道具"},
    ]

    filtered = main._filter_auto_manga_asset_suggestions(
        suggestions,
        {"character_reference", "prop_reference"},
    )

    assert [item["asset_type"] for item in filtered] == ["character_reference", "prop_reference"]


@pytest.mark.asyncio
async def test_auto_asset_analysis_reuses_persisted_suggestions_without_ai_call(monkeypatch):
    chapter = SimpleNamespace(
        id=49,
        manga_asset_analysis_json={
            "version": 1,
            "suggestions": [{
                "asset_type": "character_reference",
                "name": "陈玄",
                "prompt": "角色设定图",
            }],
        },
    )

    class FakeDB:
        commits = 0

        def commit(self):
            self.commits += 1

    async def unexpected_analyze(**_kwargs):
        raise AssertionError("缓存命中时不应调用文本 AI")

    monkeypatch.setattr(main, "analyze_visual_assets", unexpected_analyze)
    db = FakeDB()

    suggestions, fingerprint, cached = await main._load_or_analyze_auto_manga_assets(
        chapter=chapter,
        chapter_text="章节正文",
        character_context="角色资料",
        structured_characters=[{"name": "陈玄"}],
        selected_types=set(main._AUTO_MANGA_ASSET_TYPE_MAP.values()),
        request=SimpleNamespace(),
        user_id=7,
        db=db,
    )

    assert cached is True
    assert suggestions[0]["name"] == "陈玄"
    assert chapter.manga_asset_analysis_json["input_hash"] == fingerprint
    assert chapter.manga_asset_analysis_json["status"] == "ready"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_auto_asset_analysis_reuses_ready_empty_result_without_ai_call(monkeypatch):
    chapter_text = "没有需要提取资产的章节正文"
    character_context = ""
    structured_characters: list[dict[str, object]] = []
    fingerprint = main._manga_asset_analysis_fingerprint(
        chapter_text,
        character_context,
        structured_characters,
    )
    chapter = SimpleNamespace(
        id=49,
        manga_asset_analysis_json={
            "version": main.AUTO_MANGA_ASSET_ANALYSIS_VERSION,
            "input_hash": fingerprint,
            "status": "ready",
            "suggestions": [],
        },
    )

    class FakeDB:
        commits = 0

        def commit(self):
            self.commits += 1

    async def unexpected_analyze(**_kwargs):
        raise AssertionError("空分析结果命中缓存时不应再次调用文本 AI")

    monkeypatch.setattr(main, "analyze_visual_assets", unexpected_analyze)
    db = FakeDB()

    suggestions, returned_fingerprint, cached = await main._load_or_analyze_auto_manga_assets(
        chapter=chapter,
        chapter_text=chapter_text,
        character_context=character_context,
        structured_characters=structured_characters,
        selected_types=set(main._AUTO_MANGA_ASSET_TYPE_MAP.values()),
        request=SimpleNamespace(),
        user_id=7,
        db=db,
    )

    assert suggestions == []
    assert returned_fingerprint == fingerprint
    assert cached is True
    assert db.commits == 1


@pytest.mark.asyncio
async def test_auto_asset_analysis_calls_ai_once_and_persists_fingerprint(monkeypatch):
    chapter = SimpleNamespace(id=49, manga_asset_analysis_json=None)
    quota_steps: list[bool] = []

    class FakeDB:
        def commit(self):
            return None

    def fake_quota(*_args, **kwargs):
        quota_steps.append(bool(kwargs["deduct"]))
        return {"usage_event_id": 1}

    async def fake_analyze(**_kwargs):
        return {
            "characters": [{"name": "陈玄", "prompt": "角色设定图", "description": "主角"}],
            "scenes": [],
            "props": [],
        }

    monkeypatch.setattr(main, "_check_and_consume_feature_quota", fake_quota)
    monkeypatch.setattr(main, "_user_deepseek_api_key", lambda _request: "text-key")
    monkeypatch.setattr(main, "analyze_visual_assets", fake_analyze)

    suggestions, fingerprint, cached = await main._load_or_analyze_auto_manga_assets(
        chapter=chapter,
        chapter_text="章节正文",
        character_context="角色资料",
        structured_characters=[{"name": "陈玄"}],
        selected_types={"character_reference"},
        request=SimpleNamespace(),
        user_id=7,
        db=FakeDB(),
    )

    assert cached is False
    assert quota_steps == [False, True]
    assert suggestions == [{
        "asset_type": "character_reference",
        "name": "陈玄",
        "description": "主角",
        "evidence": "",
        "prompt": "角色设定图",
        "candidates": [],
    }]
    assert chapter.manga_asset_analysis_json["input_hash"] == fingerprint
    assert chapter.manga_asset_analysis_json["status"] == "ready"


def test_prepare_auto_asset_plan_reuses_exact_story_asset_and_binds(monkeypatch, tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    asset_path = tmp_path / "chenxuan.png"
    asset_path.write_bytes(b"image")
    db = Session()
    asset = MangaAsset(
        owner_user_id=7,
        story_id=15,
        chapter_id=None,
        asset_type="character_reference",
        name="陈玄",
        storage_path="https://cdn.example.com/chenxuan.png",
        source_type="upload",
        status="active",
    )
    db.add(asset)
    db.commit()
    monkeypatch.setattr(main, "ensure_local_media_path", lambda *_args: str(asset_path))

    missing, reused, anchor = main._prepare_auto_manga_asset_plan(
        db,
        user_id=7,
        story_id=15,
        chapter_id=49,
        suggestions=[{
            "asset_type": "character_reference",
            "name": "陈玄",
            "prompt": "角色设定图",
        }],
    )

    assert missing == []
    assert reused == 1
    assert anchor == str(asset_path)
    binding = db.query(MangaAssetBinding).one()
    assert binding.asset_id == asset.id
    assert binding.chapter_id == 49
    assert binding.binding_role == "character"
    assert binding.is_required is False
    db.close()


@pytest.mark.asyncio
async def test_auto_asset_generation_uses_style_anchor_and_persists_binding(monkeypatch, tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    captured: dict[str, object] = {}
    style_path = tmp_path / "style.png"
    style_path.write_bytes(b"style")
    async def fake_generate_visual_asset_image(**kwargs):
        captured.update(kwargs)
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_bytes(b"generated")
        return str(kwargs["output_path"])

    monkeypatch.setattr(main, "SessionLocal", Session)
    monkeypatch.setattr(main, "manga_dir", tmp_path / "manga_outputs")
    monkeypatch.setattr(main, "generate_visual_asset_image", fake_generate_visual_asset_image)
    monkeypatch.setattr(main, "ensure_local_media_path", lambda value, _kind: value if Path(value).exists() else None)

    result = await main._generate_auto_manga_asset(
        chapter_id=49,
        story_id=15,
        user_id=7,
        item={
            "asset_type": "scene_reference",
            "name": "地下擂台",
            "prompt": "场景设定图",
            "description": "地下空间",
            "evidence": "原文出现",
        },
        image_api_key="image-key",
        style_anchor_path=str(style_path),
    )

    assert result["status"] == "generated"
    assert captured["reference_paths"] == [str(style_path)]
    assert captured["reference_roles"] == ["style"]
    db = Session()
    assert db.query(MangaAsset).count() == 1
    binding = db.query(MangaAssetBinding).one()
    assert binding.binding_role == "scene"
    assert binding.label == "地下擂台"
    db.close()


@pytest.mark.asyncio
async def test_auto_asset_preflight_creates_first_anchor_then_reuses_it(monkeypatch, tmp_path: Path):
    anchors: list[str | None] = []
    settled: list[int] = []

    async def fake_generate(**kwargs):
        anchors.append(kwargs["style_anchor_path"])
        index = len(anchors)
        return {
            "status": "generated",
            "asset_id": index,
            "resolved_path": str(tmp_path / f"asset-{index}.png"),
        }

    monkeypatch.setattr(main, "_generate_auto_manga_asset", fake_generate)
    monkeypatch.setattr(main, "AUTO_MANGA_ASSET_START_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(main.task_manager, "update_task_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.task_manager, "is_cancellation_requested", lambda *_args: False)
    monkeypatch.setattr(
        main,
        "_finish_streaming_platform_points",
        lambda _ctx, **kwargs: settled.append(kwargs["image_count"]),
    )

    result = await main._ensure_auto_manga_assets(
        chapter_id=49,
        story_id=15,
        user_id=7,
        items=[
            {"asset_type": "character_reference", "name": "陈玄", "prompt": "角色图"},
            {"asset_type": "scene_reference", "name": "地下擂台", "prompt": "场景图"},
        ],
        image_api_key="image-key",
        style_ref_path=None,
        fallback_anchor_path=None,
        billing_ctx=object(),
        task_id="asset-preflight-test",
    )

    assert anchors == [None, str(tmp_path / "asset-1.png")]
    assert result["generated"] == 2
    assert settled == [2]


@pytest.mark.asyncio
async def test_auto_asset_preflight_partial_failure_settles_only_generated(monkeypatch):
    settled: list[int] = []

    async def fake_generate(**kwargs):
        if kwargs["item"]["name"] == "失败场景":
            raise RuntimeError("upstream failed")
        return {"status": "generated", "asset_id": 9, "resolved_path": "C:/cache/character.png"}

    monkeypatch.setattr(main, "_generate_auto_manga_asset", fake_generate)
    monkeypatch.setattr(main, "AUTO_MANGA_ASSET_START_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(main.task_manager, "update_task_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.task_manager, "is_cancellation_requested", lambda *_args: False)
    monkeypatch.setattr(
        main,
        "_finish_streaming_platform_points",
        lambda _ctx, **kwargs: settled.append(kwargs["image_count"]),
    )

    with pytest.raises(Exception, match="章节资产生成失败"):
        await main._ensure_auto_manga_assets(
            chapter_id=49,
            story_id=15,
            user_id=7,
            items=[
                {"asset_type": "character_reference", "name": "陈玄", "prompt": "角色图"},
                {"asset_type": "scene_reference", "name": "失败场景", "prompt": "场景图"},
            ],
            image_api_key="image-key",
            style_ref_path="C:/cache/style.png",
            fallback_anchor_path=None,
            billing_ctx=object(),
            task_id="asset-preflight-failure",
        )

    assert settled == [1]


@pytest.mark.asyncio
async def test_auto_asset_cancellation_settles_completed_children_and_cancels_pending(monkeypatch):
    accounted = asyncio.Event()
    pending_cancelled = asyncio.Event()
    settlements: list[dict[str, object]] = []

    async def fake_generate(**kwargs):
        if kwargs["item"]["name"] == "已完成":
            return {"status": "generated", "asset_id": 101, "resolved_path": "done.png"}
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pending_cancelled.set()
            raise

    def fake_update(_task_id, **kwargs):
        if kwargs.get("asset_generated") == 1 and kwargs.get("asset_completed") == 1:
            accounted.set()

    monkeypatch.setattr(main, "_generate_auto_manga_asset", fake_generate)
    monkeypatch.setattr(main, "AUTO_MANGA_ASSET_START_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(main.task_manager, "is_cancellation_requested", lambda _task_id: False)
    monkeypatch.setattr(main.task_manager, "update_task_metadata", fake_update)
    monkeypatch.setattr(
        main,
        "_finish_streaming_platform_points",
        lambda _ctx, **kwargs: settlements.append(kwargs),
    )

    task = asyncio.create_task(main._ensure_auto_manga_assets(
        chapter_id=1,
        story_id=2,
        user_id=3,
        items=[
            {"name": "已完成", "asset_type": "character_reference", "prompt": "完成"},
            {"name": "未完成", "asset_type": "scene_reference", "prompt": "等待"},
        ],
        image_api_key=None,
        style_ref_path="style.png",
        fallback_anchor_path=None,
        billing_ctx=object(),
        task_id="task-1",
    ))
    await asyncio.wait_for(accounted.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert pending_cancelled.is_set()
    assert settlements == [{"success": True, "image_count": 1}]

def test_reference_role_instructions_keep_asset_semantics_separate():
    character = image2._reference_role_instruction("character", "林秋", 1)
    scene = image2._reference_role_instruction("scene", "王宫大厅", 2)
    prop = image2._reference_role_instruction("prop", "银色怀表", 3)
    style = image2._reference_role_instruction("style", "水墨风格", 4)

    assert "CHARACTER" in character and "face geometry" in character
    assert "authoritative identity reference" in character
    assert "conflicting appearance details" in character
    assert "ENVIRONMENT" in scene and "do not treat it as a character" in scene
    assert "PROP" in prop and "do not treat it as a character" in prop
    assert "ART STYLE" in style and "do not copy its characters" in style


def test_text_character_profiles_remain_when_only_non_character_refs_are_used():
    prompt = image2._build_full_prompt(
        "雨夜街道",
        image_number=1,
        total_pages=1,
        all_scenes=None,
        character_profiles="角色名：林秋\n黑色长发",
        use_ref=True,
        color_mode="color",
        ref_layout_desc="Reference image 1 defines ENVIRONMENT.",
        has_style_ref=False,
        has_character_ref=False,
    )

    assert "角色名：林秋" in prompt


def test_style_reference_uses_image_style_without_fixed_manga_style():
    prompt = image2._build_full_prompt(
        "雨夜街道",
        image_number=1,
        total_pages=1,
        all_scenes=None,
        character_profiles="",
        use_ref=True,
        color_mode="bw",
        ref_layout_desc="Reference image 1 is ART STYLE reference.",
        has_style_ref=True,
    )

    assert "黑白或灰度输出" in prompt
    assert "以【画面风格参考锚点】为准" in prompt
    assert "日式黑白" not in prompt
    assert "网点" not in prompt


def test_scene_split_prompt_does_not_force_visual_style():
    seed_path = Path(__file__).resolve().parents[1] / "seed_data" / "storyboard_presets.json"
    presets = json.loads(seed_path.read_text(encoding="utf-8"))
    prompt = next(preset["prompt_template"] for preset in presets if preset["preset_key"] == "default")

    assert "构图、镜头和叙事信息" in prompt
    assert "日式黑白" not in prompt
    assert "网点" not in prompt


def test_style_reference_profile_compression_preserves_identity_and_removes_style():
    compressed = image2._compress_character_profiles_for_style_reference(
        "林秋：侦探，黑色长发，身穿白衬衫，随身携带银色怀表。\n"
        "画风：日式漫画，精细线稿，16:9 画面比例。"
    )

    assert "林秋" in compressed
    assert "白衬衫" in compressed
    assert "银色怀表" in compressed
    assert "日式漫画" not in compressed
    assert "画面比例" not in compressed


def test_style_reference_prompt_uses_only_current_scene_context():
    prompt = image2._build_full_prompt(
        "当前页雨夜追逐",
        image_number=2,
        total_pages=3,
        all_scenes=["前一页固定日式画风", "当前页雨夜追逐", "后一页水彩画风"],
        character_profiles="",
        use_ref=True,
        color_mode="color",
        has_style_ref=True,
    )

    assert "当前页雨夜追逐" in prompt
    assert "前一页固定日式画风" not in prompt
    assert "后一页水彩画风" not in prompt
    assert prompt.count("当前页雨夜追逐") == 1


def test_style_reference_prompt_matches_visible_visual_language_without_text_preset():
    prompt = image2._build_full_prompt(
        "雨夜追逐",
        image_number=1,
        total_pages=1,
        all_scenes=["雨夜追逐"],
        character_profiles="",
        use_ref=True,
        color_mode="color",
        has_style_ref=True,
    )

    assert "人物造型比例" in prompt
    assert "五官简化方式" in prompt
    assert "笔触颗粒" in prompt
    assert "预设名称" in prompt
    assert "borrow their painting style" not in prompt


def test_reference_blob_resolution_depends_on_role(tmp_path: Path):
    style_path = tmp_path / "style.png"
    character_path = tmp_path / "character.png"
    Image.new("RGB", (400, 200), "red").save(style_path)
    Image.new("RGB", (1200, 600), "blue").save(character_path)

    blobs = image2._prepare_ref_blobs(
        [style_path, character_path],
        "test",
        ["style", "character"],
    )

    with Image.open(io.BytesIO(blobs[0][1])) as style_image:
        assert max(style_image.size) == 1024
    with Image.open(io.BytesIO(blobs[1][1])) as character_image:
        assert max(character_image.size) == 1024


def test_manga_edit_payload_omits_fidelity_for_style_only(monkeypatch):
    monkeypatch.setattr(image2, "runtime_model", lambda: "image-model")

    payload = image2._manga_edit_payload("提示词", "1024x1024", ["style"])

    assert payload == {"model": "image-model", "prompt": "提示词", "size": "1024x1024"}


def test_manga_edit_payload_keeps_runtime_fidelity_for_mixed_refs(monkeypatch):
    monkeypatch.setattr(image2, "runtime_model", lambda: "image-model")
    monkeypatch.setattr(image2, "_runtime_settings", lambda: SimpleNamespace(input_fidelity="low"))

    payload = image2._manga_edit_payload("提示词", "1024x1024", ["style", "character"])

    assert payload["input_fidelity"] == "low"


@pytest.mark.asyncio
async def test_style_only_reference_request_omits_input_fidelity(monkeypatch, tmp_path: Path):
    style_path = tmp_path / "style.png"
    Image.new("RGB", (400, 200), "red").save(style_path)
    output_dir = tmp_path / "manga_outputs"
    output_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeResponse:
        is_success = True

        @staticmethod
        def json():
            return {"data": [{"url": "https://cdn.example.com/generated.png"}]}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(image2.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(image2, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(image2, "runtime_model", lambda: "image-model")
    monkeypatch.setattr(image2, "runtime_base_url", lambda: "https://image.example.com/v1")
    monkeypatch.setattr(image2, "_upload_image_url_to_oss", lambda *_args: "https://cdn.example.com/result.png")

    result = await image2.generate_reference_image(
        prompt="雨夜街道",
        output_path=output_dir / "result.png",
        api_key="test-key",
        ref_image_paths=[str(style_path)],
        ref_type="style",
        ref_roles=["style"],
    )

    assert result == "https://cdn.example.com/result.png"
    assert "input_fidelity" not in captured["data"]
    uploaded_image = captured["files"][0][1][1]
    with Image.open(io.BytesIO(uploaded_image)) as prepared:
        assert max(prepared.size) == 1024


@pytest.mark.asyncio
async def test_manga_request_uploads_character_asset_first_with_identity_mapping(monkeypatch, tmp_path: Path):
    character_path = tmp_path / "character.png"
    scene_path = tmp_path / "scene.png"
    Image.new("RGB", (1200, 700), "red").save(character_path)
    Image.new("RGB", (1200, 700), "blue").save(scene_path)
    output_dir = tmp_path / "manga_outputs"
    output_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeResponse:
        is_success = True

        @staticmethod
        def json():
            return {"data": [{"url": "https://cdn.example.com/generated.png"}]}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(image2.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(image2, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(image2, "runtime_model", lambda: "image-model")
    monkeypatch.setattr(image2, "runtime_base_url", lambda: "https://image.example.com/v1")
    monkeypatch.setattr(image2, "_upload_image_url_to_oss", lambda *_args: "https://cdn.example.com/result.png")
    monkeypatch.setattr(image2, "_runtime_settings", lambda: SimpleNamespace(size="1024x1024", input_fidelity="high"))

    await image2.generate_manga_image(
        "陈玄在出租屋醒来",
        chapter_id=52,
        image_number=1,
        all_scenes=["陈玄在出租屋醒来"],
        ref_image_paths=[str(character_path), str(scene_path)],
        ref_labels=["陈玄", "出租屋"],
        ref_roles=["character", "scene"],
        api_key="test-key",
    )

    files = captured["files"]
    assert [item[0] for item in files] == ["image[]", "image[]"]
    first_image = files[0][1][1].getvalue()
    with Image.open(io.BytesIO(first_image)) as prepared:
        assert prepared.getpixel((0, 0))[0] > prepared.getpixel((0, 0))[2]
        assert max(prepared.size) == 1024
    prompt = captured["data"]["prompt"]
    assert "Reference image 1 defines CHARACTER '陈玄'" in prompt
    assert "Reference image 2 defines ENVIRONMENT '出租屋'" in prompt
    assert captured["data"]["input_fidelity"] == "high"


def test_effective_entries_do_not_mix_legacy_refs_when_new_binding_exists(monkeypatch, tmp_path: Path):
    chapter_ref_dir = tmp_path / "chapter_refs"
    story_ref_dir = tmp_path / "story_refs"
    chapter_ref_dir.mkdir()
    story_ref_dir.mkdir()
    (chapter_ref_dir / "legacy.png").write_bytes(b"legacy")
    asset_path = tmp_path / "asset.png"
    asset_path.write_bytes(b"asset")

    binding = SimpleNamespace(
        binding_role="character",
        label="林秋",
        priority=3,
        is_required=True,
        id=1,
    )
    asset = SimpleNamespace(
        id=9,
        storage_path="https://cdn.example.com/asset.png",
        name="林秋设定图",
    )

    class FakeQuery:
        def join(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [(binding, asset)]

    class FakeDB:
        def get(self, model, value):
            return SimpleNamespace(story_id=7)

        def query(self, *args, **kwargs):
            return FakeQuery()

    monkeypatch.setattr(main, "_chapter_ref_dir", lambda chapter_id: chapter_ref_dir)
    monkeypatch.setattr(main, "_story_ref_dir", lambda story_id: story_ref_dir)
    monkeypatch.setattr(main, "_legacy_chapter_ref_image", lambda chapter_id: tmp_path / "missing-chapter.png")
    monkeypatch.setattr(main, "_legacy_story_ref_image", lambda story_id: tmp_path / "missing-story.png")
    monkeypatch.setattr(main, "ensure_local_media_path", lambda value, kind: str(asset_path))

    entries = main._effective_ref_entries(11, FakeDB())

    assert len(entries) == 1
    assert entries[0]["path"] == asset_path
    assert entries[0]["kind"] == "character"
    assert entries[0]["is_required"] is True
