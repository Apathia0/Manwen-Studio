"""使用命令替身验证合片安全契约，不调用真实编码器或付费服务。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import video_compiler as compiler


def media_info(duration=2.0, audio=True, width=1280, height=720):
    streams = [{"codec_type": "video", "width": width, "height": height, "duration": str(duration)}]
    if audio:
        streams.append({"codec_type": "audio", "duration": str(duration)})
    return {"streams": streams, "format": {"duration": str(duration)}}


@pytest.fixture
def command_harness(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    target = tmp_path / "final.mp4"
    target.write_bytes(b"previous-success")
    state = SimpleNamespace(
        source=source, target=target, commands=[], sources={str(source): media_info()},
        final=media_info(), fail=None, omit_output=False,
    )

    async def run(command):
        state.commands.append(command)
        if "-show_streams" in command:
            payload = state.sources.get(command[-1], state.final)
            return json.dumps(payload).encode("utf-8")
        if state.fail:
            raise state.fail
        # 发布前所有编码步骤必须保持已有结果完整。
        assert target.read_bytes() == b"previous-success"
        if not state.omit_output:
            Path(command[-1]).write_bytes(b"validated-result")
        return b""

    monkeypatch.setattr(compiler, "_run_process", run)
    monkeypatch.setattr(compiler, "_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(compiler, "_ffprobe_path", lambda: "ffprobe")
    return state


def compile_with(state, **kwargs):
    clips = kwargs.pop("clips", [{"video_path": str(state.source), "duration_seconds": 999}])
    return asyncio.run(compiler.compile_project(str(state.target), clips, **kwargs))


def test_default_preserves_audio_and_uses_probed_duration(command_harness):
    state = command_harness
    result = compile_with(state)
    commands = [cmd for cmd in state.commands if cmd[0] == "ffmpeg"]
    assert len(commands) == 2
    assert all("-an" not in cmd for cmd in commands)
    assert "0:a:0" in commands[-1]
    assert "-filter_complex" not in commands[-1]
    assert result["duration_seconds"] == 2.0
    assert result["status"] == "compiled"
    assert result["clip_count"] == 1
    assert state.target.read_bytes() == b"validated-result"
    assert not list(state.target.parent.glob(".compile_*"))


def test_mixed_audio_and_resolutions_are_normalized_before_concat(command_harness):
    state = command_harness
    silent = state.source.with_name("silent.mp4")
    silent.write_bytes(b"silent")
    state.sources[str(state.source)] = media_info(width=640, height=480)
    state.sources[str(silent)] = media_info(audio=False, width=1080, height=1920)
    state.final = media_info(duration=4)
    compile_with(state, clips=[{"video_path": str(state.source)}, {"video_path": str(silent)}])
    commands = [cmd for cmd in state.commands if cmd[0] == "ffmpeg"]
    for cmd in commands[:2]:
        assert "libx264" in cmd and "aac" in cmd
        assert "scale=1280:720" in cmd[cmd.index("-vf") + 1]
        assert "fps=24" in cmd[cmd.index("-vf") + 1]
        assert cmd[cmd.index("-ac") + 1] == "2"
    assert "lavfi" not in commands[0]
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in commands[1]
    assert "1:a:0" in commands[1]


def test_subtitles_and_bgm_use_separate_video_and_audio_filters(command_harness):
    state = command_harness
    music = state.source.with_name("music.aac")
    music.write_bytes(b"music")
    state.sources[str(music)] = {"streams": [{"codec_type": "audio", "duration": "1"}]}
    compile_with(state, bgm_path=str(music), subtitle_data=[{"start_ms": 0, "end_ms": 1000, "text": "对白"}])
    command = [cmd for cmd in state.commands if cmd[0] == "ffmpeg"][-1]
    assert "amix=" in command[command.index("-filter_complex") + 1]
    assert "normalize=0" in command[command.index("-filter_complex") + 1]
    assert "subtitles=" in command[command.index("-vf") + 1]
    assert "amix" not in command[command.index("-vf") + 1]
    assert "[mixed]" in command
    assert "-stream_loop" in command


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("failure", [RuntimeError("转码失败"), FileNotFoundError("ffmpeg"), asyncio.CancelledError()])
def test_failures_raise_and_preserve_existing_output(command_harness, strict, failure):
    state = command_harness
    state.fail = failure
    with pytest.raises(type(failure)):
        compile_with(state, strict=strict)
    assert state.target.read_bytes() == b"previous-success"
    assert not list(state.target.parent.glob(".compile_*"))


def test_strict_rejects_one_missing_clip_without_partial_publish(command_harness):
    state = command_harness
    with pytest.raises(RuntimeError, match="片段缺失"):
        compile_with(state, strict=True, clips=[{"video_path": str(state.source)}, {"video_path": "missing.mp4"}])
    assert state.target.read_bytes() == b"previous-success"
    assert not any(cmd[0] == "ffmpeg" for cmd in state.commands)


def test_non_strict_skip_missing_does_not_inflate_duration(command_harness):
    result = compile_with(command_harness, clips=[
        {"video_path": "missing.mp4", "duration_seconds": 99},
        {"video_path": str(command_harness.source), "duration_seconds": 99},
    ])
    assert result["clip_count"] == 1
    assert result["duration_seconds"] == 2


@pytest.mark.parametrize("strict", [False, True])
def test_no_clips_never_creates_placeholder(command_harness, strict):
    with pytest.raises(RuntimeError, match="没有可用于拼接"):
        compile_with(command_harness, clips=[], strict=strict)
    assert command_harness.target.read_bytes() == b"previous-success"


@pytest.mark.parametrize("payload", [
    {"streams": []},
    media_info(duration=0),
    media_info(duration="NaN"),
    media_info(duration="inf"),
    media_info(width=0),
    {"streams": [{"codec_type": "audio", "duration": "2"}]},
    {"streams": [{"codec_type": "video", "duration": "2", "width": 640, "height": 480, "disposition": {"attached_pic": 1}}]},
])
def test_invalid_input_media_is_rejected(command_harness, payload):
    state = command_harness
    state.sources[str(state.source)] = payload
    with pytest.raises(RuntimeError, match="不是有效的视频"):
        compile_with(state)
    assert state.target.read_bytes() == b"previous-success"


@pytest.mark.parametrize("payload", [media_info(duration=0.1), media_info(audio=False), media_info(width=640)])
def test_invalid_final_media_never_replaces_success(command_harness, payload):
    state = command_harness
    state.final = payload
    with pytest.raises(RuntimeError):
        compile_with(state)
    assert state.target.read_bytes() == b"previous-success"
    assert not list(state.target.parent.glob(".compile_*"))


def test_success_exit_without_output_is_failure(command_harness):
    state = command_harness
    state.omit_output = True
    with pytest.raises(RuntimeError, match="没有生成有效输出"):
        compile_with(state)
    assert state.target.read_bytes() == b"previous-success"


def test_missing_bgm_is_not_silently_ignored(command_harness):
    with pytest.raises(RuntimeError, match="不存在"):
        compile_with(command_harness, bgm_path="missing.aac")


def test_process_errors_are_not_returned_as_success(monkeypatch):
    async def communicate():
        return b"", b"invalid video"

    async def create(*args, **kwargs):
        return SimpleNamespace(communicate=communicate, returncode=1)

    monkeypatch.setattr(compiler.asyncio, "create_subprocess_exec", create)
    with pytest.raises(RuntimeError, match="invalid video"):
        asyncio.run(compiler._run_process(["ffmpeg"]))


def test_missing_executable_is_reported(monkeypatch):
    async def create(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(compiler.asyncio, "create_subprocess_exec", create)
    with pytest.raises(RuntimeError, match="缺少 ffmpeg 或 ffprobe"):
        asyncio.run(compiler._run_process(["ffprobe"]))


def test_cancelled_process_is_killed_and_drained(monkeypatch):
    state = SimpleNamespace(returncode=None, calls=0, killed=False)

    async def communicate():
        state.calls += 1
        if state.calls == 1:
            raise asyncio.CancelledError()
        return b"", b""

    def kill():
        state.killed = True
        state.returncode = -9

    async def create(*args, **kwargs):
        return state

    state.communicate = communicate
    state.kill = kill
    monkeypatch.setattr(compiler.asyncio, "create_subprocess_exec", create)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(compiler._run_process(["ffmpeg"]))
    assert state.killed and state.calls == 2


def test_subtitle_timestamp_preserves_integer_milliseconds():
    path = compiler._create_srt_file([{"start_ms": 999, "end_ms": 1234, "text": "对白"}])
    try:
        data = Path(path).read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf")
        assert "00:00:00,999 --> 00:00:01,234" in data.decode("utf-8")
    finally:
        Path(path).unlink()
