"""画布审片附件只读取媒体目录，关键帧不冒充完整视听审查。"""

from types import SimpleNamespace

import pytest

from services import canvas_media_context as media


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    base = tmp_path / "backend"
    (base / "services").mkdir(parents=True)
    (base / "manga_outputs").mkdir()
    (base / "video_outputs").mkdir()
    monkeypatch.setattr(media, "__file__", str(base / "services" / "canvas_media_context.py"))
    return base


@pytest.mark.parametrize("prefix", ["/static/manga/", "manga_outputs/", ""])
def test_owned_media_paths(media_root, prefix):
    image = media_root / "manga_outputs" / "参考.png"
    image.write_bytes(b"image")
    assert media._local_media_path(prefix + "参考.png") == image.resolve()


def test_outside_paths_and_missing_media_are_rejected(media_root):
    secret = media_root / "private.txt"
    secret.write_bytes(b"private")
    for path in [str(secret), "/static/manga/../private.txt", "../private.txt", "https://example.com/a.png", "missing.png"]:
        assert media._local_media_path(path) is None


@pytest.mark.asyncio
async def test_video_frames_are_images_without_fabricated_audio_instruction(media_root, tmp_path, monkeypatch):
    from services import agent_media
    movie = media_root / "video_outputs" / "clip.mp4"
    movie.write_bytes(b"video")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    graph = {"nodes": [{"id": "video-1", "type": "video", "data": {"config": {"prompt": "镜头"}}}], "edges": []}
    canvas = SimpleNamespace(id=1, story_id=1, definition_revision=3)
    version = SimpleNamespace(id=3, graph_json=graph, version_no=3)
    run = SimpleNamespace(id=2, canvas_id=1, canvas_version_id=3)
    node = SimpleNamespace(id=4, node_id="video-1", status="succeeded", attempt=1, output_snapshot_json={"file_path": str(movie)})

    class Query:
        def __init__(self, values):
            self.values = values

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return self.values

        def first(self):
            return self.values[0] if self.values else None

    db = SimpleNamespace(
        get=lambda model, key: (
            canvas if model is media.VideoCanvas
            else version if model is media.VideoCanvasVersion
            else SimpleNamespace(story_id=1)
        ),
        query=lambda model: Query(
            [version] if model is media.VideoCanvasVersion
            else [run] if model is media.VideoCanvasRun
            else [node]
        ),
    )
    monkeypatch.setattr(media, "_node_definition_hash", lambda _graph, _node_id: "same")
    monkeypatch.setattr(agent_media, "_probe_video", lambda path: {"duration": 4.0})
    monkeypatch.setattr(agent_media, "_extract_video_frames", lambda *args: [str(frame)])
    monkeypatch.setattr(media.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "review"))
    result = await media.build_canvas_media_context(db, 1)
    assert result["attachments"][0]["media_kind"] == "image"
    assert result["attachments"][0]["path"] == str(frame)
    assert "关键帧不能证明对白" in result["summary"]
    assert result["temporary_paths"] == [str(tmp_path / "review")]


@pytest.mark.asyncio
async def test_stale_definition_never_attaches_image(media_root, monkeypatch):
    image = media_root / "manga_outputs" / "old.png"
    image.write_bytes(b"image")
    current_graph = {"hashes": {"image-1": "current"}, "nodes": [{"id": "image-1", "type": "image"}], "edges": []}
    old_graph = {"hashes": {"image-1": "old"}, "nodes": [{"id": "image-1", "type": "image"}], "edges": []}
    canvas = SimpleNamespace(id=1, story_id=1, definition_revision=2)
    current_version = SimpleNamespace(id=2, graph_json=current_graph, version_no=2)
    old_version = SimpleNamespace(id=1, graph_json=old_graph, version_no=1)
    run = SimpleNamespace(id=8, canvas_id=1, canvas_version_id=1)
    node = SimpleNamespace(id=9, node_id="image-1", status="succeeded", attempt=1, output_snapshot_json={"file_path": str(image)})

    class Query:
        def __init__(self, values):
            self.values = values

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return self.values

        def first(self):
            return self.values[0] if self.values else None

    db = SimpleNamespace(
        get=lambda model, key: (
            canvas if model is media.VideoCanvas
            else old_version if model is media.VideoCanvasVersion and key == 1
            else current_version if model is media.VideoCanvasVersion
            else SimpleNamespace(story_id=1)
        ),
        query=lambda model: Query(
            [current_version] if model is media.VideoCanvasVersion
            else [run] if model is media.VideoCanvasRun
            else [node]
        ),
    )
    monkeypatch.setattr(media, "_node_definition_hash", lambda graph, node_id: graph["hashes"][node_id])
    result = await media.inspect_media(db, 1, ["image-1"], 2)
    assert result["attachments"] == []
    assert result["nodes"][0]["state"] == "stale"
    assert "旧产物不能冒充当前图" in result["nodes"][0]["reason"]


@pytest.mark.asyncio
async def test_revision_conflict_returns_without_attachments(media_root):
    canvas = SimpleNamespace(id=1, story_id=1, definition_revision=3)

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return SimpleNamespace(graph_json={"nodes": [], "edges": []})

    db = SimpleNamespace(get=lambda model, key: canvas, query=lambda model: Query())
    result = await media.inspect_media(db, 1, ["image-1"], 2)
    assert result["ok"] is False
    assert result["conflict"] is True
    assert result["attachments"] == []
    assert result["receipts"] == []


@pytest.mark.asyncio
async def test_invalid_asset_id_does_not_fallback_to_raw_path(media_root, monkeypatch):
    image = media_root / "manga_outputs" / "raw.png"
    image.write_bytes(b"image")
    graph = {"nodes": [{"id": "image-1", "type": "image"}], "edges": []}
    canvas = SimpleNamespace(id=1, story_id=1, definition_revision=1)
    version = SimpleNamespace(id=1, graph_json=graph, version_no=1)
    run = SimpleNamespace(id=1, canvas_id=1, canvas_version_id=1)
    node = SimpleNamespace(id=1, node_id="image-1", status="succeeded", attempt=1, output_snapshot_json={"asset_id": 99, "file_path": str(image)})

    class Query:
        def __init__(self, values):
            self.values = values

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return self.values

        def first(self):
            return self.values[0] if self.values else None

    db = SimpleNamespace(
        get=lambda model, key: (
            canvas if model is media.VideoCanvas
            else version if model is media.VideoCanvasVersion
            else None
        ),
        query=lambda model: Query([version] if model is media.VideoCanvasVersion else [run] if model is media.VideoCanvasRun else [node]),
    )
    monkeypatch.setattr(media, "_node_definition_hash", lambda _graph, _node_id: "same")
    result = await media.inspect_media(db, 1, ["image-1"], 1)
    assert result["attachments"] == []
    assert "资产不存在" in result["nodes"][0]["reason"]


@pytest.mark.asyncio
async def test_current_config_asset_mismatch_blocks_attachment(media_root, monkeypatch):
    image = media_root / "manga_outputs" / "asset.png"
    image.write_bytes(b"image")
    graph = {"nodes": [{"id": "image-1", "type": "image", "data": {"config": {"asset_id": 12}}}], "edges": []}
    canvas = SimpleNamespace(id=1, story_id=1, definition_revision=1)
    version = SimpleNamespace(id=1, graph_json=graph, version_no=1)
    run = SimpleNamespace(id=1, canvas_id=1, canvas_version_id=1)
    node = SimpleNamespace(id=1, node_id="image-1", status="succeeded", attempt=1, output_snapshot_json={"asset_id": 11})
    asset = SimpleNamespace(id=11, story_id=1, status="active", file_path=str(image))

    class Query:
        def __init__(self, values):
            self.values = values

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return self.values

        def first(self):
            return self.values[0] if self.values else None

    db = SimpleNamespace(
        get=lambda model, key: (
            canvas if model is media.VideoCanvas
            else version if model is media.VideoCanvasVersion
            else asset if model is media.VideoAsset
            else None
        ),
        query=lambda model: Query([version] if model is media.VideoCanvasVersion else [run] if model is media.VideoCanvasRun else [node]),
    )
    monkeypatch.setattr(media, "_node_definition_hash", lambda _graph, _node_id: "same")
    result = await media.inspect_media(db, 1, ["image-1"], 1)
    assert result["attachments"] == []
    assert "绑定资产" in result["nodes"][0]["reason"]


@pytest.mark.asyncio
async def test_round_context_only_lists_media_when_nothing_selected(monkeypatch):
    """每轮不再自动附前 6 张图：没选中节点时只给清单，由助手按需调用 inspect_canvas_media。"""
    graph = {"nodes": [{"id": f"image-{i}", "type": "image", "data": {"label": f"分镜{i}"}} for i in range(10)] + [{"id": "s", "type": "screenplay", "data": {}}], "edges": []}
    canvas = SimpleNamespace(id=1, definition_revision=3)
    monkeypatch.setattr(media, "_latest_graph", lambda db, c: graph)
    calls = []

    async def fake_inspect(db, canvas_id, node_ids, expected):
        calls.append(list(node_ids))
        return {"attachments": [{"node_id": node_ids[0]}], "temporary_paths": [], "summary": "ok"}

    monkeypatch.setattr(media, "inspect_media", fake_inspect)
    db = SimpleNamespace(get=lambda model, key: canvas)
    listed = await media.build_canvas_media_context(db, 1, [])
    assert listed["attachments"] == [] and calls == []
    assert "共有 10 个图片/视频节点" in listed["summary"] and "image-9" in listed["summary"] and "数量不限" in listed["summary"]
    selected = await media.build_canvas_media_context(db, 1, ["image-7", "s", "ghost"])
    assert calls == [["image-7"]] and selected["attachments"] == [{"node_id": "image-7"}]
