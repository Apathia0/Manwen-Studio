import services.image2 as image2
import pytest


def _reset_image_runtime():
    image2.IMAGE_API_BASE_URL = "https://newapi.aifusion6.cn/v1"
    image2.IMAGE_MODEL = "gpt-image-2"
    image2.IMAGE_SIZE = image2.DEFAULT_IMAGE_SIZE
    image2.IMAGE_QUALITY = ""
    image2.IMAGE_BACKGROUND = ""
    image2.IMAGE_MODERATION = ""
    image2.IMAGE_OUTPUT_FORMAT = ""
    image2.IMAGE_OUTPUT_COMPRESSION = None
    image2.IMAGE_INPUT_FIDELITY = ""
    image2._IMAGE_RUNTIME.set(None)


@pytest.fixture(autouse=True)
def image_runtime_isolated():
    """每个用例恢复图片运行时，避免 ContextVar 配置泄漏到其他测试。"""
    _reset_image_runtime()
    yield
    _reset_image_runtime()


def test_generation_payload_keeps_legacy_shape_when_unconfigured():
    _reset_image_runtime()

    payload = image2._generation_payload("draw a cat", "1024x1024")

    assert payload == {
        "model": "gpt-image-2",
        "prompt": "draw a cat",
        "size": "1024x1024",
    }


def test_generation_payload_includes_configured_openai_image_params():
    _reset_image_runtime()
    image2.configure_runtime(
        model="gpt-image-2",
        size="1536x1024",
        quality="high",
        background="transparent",
        moderation="low",
        output_format="webp",
        output_compression="82",
    )

    payload = image2._generation_payload("draw a cover", None)

    assert payload["model"] == "gpt-image-2"
    assert payload["size"] == "1536x1024"
    assert payload["quality"] == "high"
    assert payload["background"] == "transparent"
    assert payload["moderation"] == "low"
    assert payload["output_format"] == "webp"
    assert payload["output_compression"] == 82


def test_edit_payload_includes_input_fidelity_and_shared_params():
    _reset_image_runtime()
    image2.configure_runtime(
        quality="medium",
        output_format="png",
        output_compression=101,
        input_fidelity="high",
    )

    payload = image2._edit_payload("adjust the face", "1024x1024")

    assert payload["quality"] == "medium"
    assert payload["output_format"] == "png"
    assert payload["output_compression"] == 100
    assert payload["input_fidelity"] == "high"


def test_manga_edit_payload_keeps_shared_quality_for_multipart_requests():
    _reset_image_runtime()
    image2.configure_runtime(quality="high", output_format="webp", input_fidelity="low")

    payload = image2._manga_edit_payload("keep character", "1024x1024", ["character"])

    assert payload["quality"] == "high"
    assert payload["output_format"] == "webp"
    assert payload["input_fidelity"] == "low"


def test_style_only_manga_edit_payload_omits_input_fidelity_but_keeps_quality():
    _reset_image_runtime()
    image2.configure_runtime(quality="medium", input_fidelity="high")

    payload = image2._manga_edit_payload("match style", "1024x1024", ["style"])

    assert payload["quality"] == "medium"
    assert "input_fidelity" not in payload


def test_custom_size_is_always_allowed_when_valid():
    """任何模型都接受合法的尺寸格式（不再按模型名硬编码限制）"""
    _reset_image_runtime()
    image2.configure_runtime(model="any-model", size="1920x1080")

    payload = image2._generation_payload("draw a frame", None)

    # 上游要求宽高为 16 的倍数：1080 对齐为 1088（配置值本身不变，只调整实际发出的尺寸）
    assert payload["size"] == "1920x1088"


def test_custom_size_is_allowed_for_gpt_image_2():
    _reset_image_runtime()
    image2.configure_runtime(model="gpt-image-2", size="1920x1080")

    payload = image2._generation_payload("draw a frame", None)

    # 上游要求宽高为 16 的倍数：1080 对齐为 1088（配置值本身不变，只调整实际发出的尺寸）
    assert payload["size"] == "1920x1088"

