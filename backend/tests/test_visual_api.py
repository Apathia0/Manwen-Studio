"""测试视觉 API 客户端服务。"""

import asyncio
import io

import pytest
from PIL import Image

from unittest.mock import MagicMock

from services.errors import MissingApiKeyError, UpstreamServiceError


def _reset_runtime():
    """重置运行时配置到未配置状态。"""
    import services.visual_api as visual_api

    visual_api._runtime_base_url = None
    visual_api._runtime_api_key = None
    visual_api._runtime_model = None


def test_configure_sets_runtime_values():
    """configure() 应正确设置全局运行时变量。"""
    from services import visual_api

    _reset_runtime()

    visual_api.configure(
        base_url="https://test.api.com/v1",
        api_key="test-key-123",
        model="gpt-4o",
    )

    assert visual_api._runtime_base_url == "https://test.api.com/v1"
    assert visual_api._runtime_api_key == "test-key-123"
    assert visual_api._runtime_model == "gpt-4o"


def test_configure_sets_only_provided_values():
    """configure() 只更新提供的参数，未提供的保持不变。"""
    from services import visual_api

    _reset_runtime()
    visual_api._runtime_base_url = "https://existing.api.com/v1"

    visual_api.configure(api_key="new-key")

    assert visual_api._runtime_base_url == "https://existing.api.com/v1"
    assert visual_api._runtime_api_key == "new-key"
    assert visual_api._runtime_model is None


def test_compress_image_resizes_large_image():
    """2048x2048 的图片应被压缩到 <= 1024 像素。"""
    from services.visual_api import _compress_image

    # 创建一张 2048x2048 的测试图片
    img = Image.new("RGB", (2048, 2048), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    large_bytes = buf.getvalue()

    compressed = _compress_image(large_bytes)

    # 验证尺寸 <= 1024
    with Image.open(io.BytesIO(compressed)) as reopened:
        assert reopened.width <= 1024
        assert reopened.height <= 1024
        assert reopened.width == reopened.height  # 保持宽高比


def test_compress_image_keeps_small_image():
    """小于 1024 的图片不应被放大。"""
    from services.visual_api import _compress_image

    img = Image.new("RGB", (512, 512), color="green")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    small_bytes = buf.getvalue()

    compressed = _compress_image(small_bytes)

    with Image.open(io.BytesIO(compressed)) as reopened:
        assert reopened.width <= 512
        assert reopened.height <= 512


def test_image_to_data_url_returns_valid_prefix():
    """data URL 应以 'data:image/jpeg;base64,' 开头。"""
    from services.visual_api import _image_to_data_url

    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img_bytes = buf.getvalue()

    data_url = _image_to_data_url(img_bytes)

    assert data_url.startswith("data:image/jpeg;base64,")


def test_analyze_images_raises_on_no_config():
    """未配置任何参数时抛出 MissingApiKeyError 或 ValueError。"""
    import services.visual_api as visual_api

    _reset_runtime()

    with pytest.raises((MissingApiKeyError, ValueError)):
        asyncio.run(
            visual_api.analyze_images(
                images=[b"fake_image_bytes"],
                prompt="describe this image",
            )
        )


def test_analyze_images_raises_missing_api_key():
    """有 base_url 和 model 但无 API Key 时抛出 MissingApiKeyError。"""
    import services.visual_api as visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
    )

    with pytest.raises(MissingApiKeyError):
        asyncio.run(
            visual_api.analyze_images(
                images=[b"fake_image_bytes"],
                prompt="describe this image",
            )
        )


def test_analyze_images_handles_string_urls():
    """分析图片应接受字符串 URL 作为图片输入。"""
    import services.visual_api as visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
        api_key="test-key",
    )

    # 使用字符串 URL 时不应抛出异常
    # 实际请求会因为 URL 不可达而抛出 UpstreamServiceError
    try:
        asyncio.run(
            visual_api.analyze_images(
                images=["https://example.com/image.jpg"],
                prompt="describe this image",
            )
        )
    except MissingApiKeyError:
        pytest.fail("不应抛出 MissingApiKeyError")
    except Exception:
        pass  # 网络错误是可预期的


def test_configure_strips_trailing_slash():
    """configure() 应去除 base_url 末尾的斜杠。"""
    from services import visual_api

    _reset_runtime()

    visual_api.configure(base_url="https://test.api.com/v1/")

    assert visual_api._runtime_base_url == "https://test.api.com/v1"


def test_compress_image_handles_rgba():
    """RGBA 图片应被正确转换为 RGB 后压缩。"""
    from services.visual_api import _compress_image

    # 创建带有透明通道的图片
    img = Image.new("RGBA", (800, 800), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    rgba_bytes = buf.getvalue()

    compressed = _compress_image(rgba_bytes)

    with Image.open(io.BytesIO(compressed)) as reopened:
        assert reopened.mode == "RGB"
        assert reopened.width <= 1024


def _make_jpeg_bytes(size: int = 128) -> bytes:
    """生成一张有效的 JPEG 测试图片。"""
    img = Image.new("RGB", (size, size), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def test_compress_image_invalid_data_raises():
    """无效图片数据应抛出 ValueError。"""
    from services.visual_api import _compress_image

    with pytest.raises(ValueError, match="无法识别图片格式"):
        _compress_image(b"not_an_image_at_all")


def test_analyze_images_success(mocker):
    """模拟 HTTP 200，验证成功解析响应。"""
    from services import visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
        api_key="test-key",
    )

    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "画面中有一个角色站在山顶眺望远方"}}]
    }
    mock_post.return_value = mock_response

    result = asyncio.run(
        visual_api.analyze_images(
            images=[_make_jpeg_bytes()],
            prompt="描述这张图片",
        )
    )

    assert result == "画面中有一个角色站在山顶眺望远方"


def test_analyze_images_raises_on_empty_choices(mocker):
    """API 返回空 choices 时应处理。"""
    from services import visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
        api_key="test-key",
    )

    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"choices": []}
    mock_post.return_value = mock_response

    with pytest.raises((IndexError, KeyError)):
        asyncio.run(
            visual_api.analyze_images(
                images=[_make_jpeg_bytes()],
                prompt="描述这张图片",
            )
        )


def test_analyze_images_raises_on_400(mocker):
    """HTTP 400 应抛出 UpstreamServiceError(retryable=False)。"""
    from services import visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
        api_key="test-key",
    )

    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 400
    mock_response.text = '{"error": "bad request"}'
    mock_post.return_value = mock_response

    with pytest.raises(UpstreamServiceError) as exc_info:
        asyncio.run(
            visual_api.analyze_images(
                images=[_make_jpeg_bytes()],
                prompt="描述这张图片",
            )
        )

    assert exc_info.value.retryable is False


def test_analyze_images_retries_on_429_then_succeeds(mocker):
    """HTTP 429 后应重试，最终成功。"""
    from services import visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
        api_key="test-key",
    )

    mock_post = mocker.patch("httpx.AsyncClient.post")
    fail_response = MagicMock()
    fail_response.is_success = False
    fail_response.status_code = 429
    fail_response.text = "rate limit"

    success_response = MagicMock()
    success_response.is_success = True
    success_response.json.return_value = {
        "choices": [{"message": {"content": "retry succeeded"}}]
    }

    mock_post.side_effect = [fail_response, success_response]

    result = asyncio.run(
        visual_api.analyze_images(
            images=[_make_jpeg_bytes()],
            prompt="描述这张图片",
        )
    )

    assert result == "retry succeeded"
    assert mock_post.call_count == 2


def test_analyze_images_passes_max_tokens(mocker):
    """验证 max_tokens 参数被传递到请求体中。"""
    from services import visual_api

    _reset_runtime()
    visual_api.configure(
        base_url="https://test.api.com/v1",
        model="gpt-4o",
        api_key="test-key",
    )

    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }
    mock_post.return_value = mock_response

    asyncio.run(
        visual_api.analyze_images(
            images=[_make_jpeg_bytes()],
            prompt="描述",
            max_tokens=2048,
        )
    )

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["max_tokens"] == 2048
