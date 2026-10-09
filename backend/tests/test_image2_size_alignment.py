import pytest

from services import image2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1920x1080", "1920x1088"),   # 1080 不是 16 的倍数，上游会 400
        ("1080x1920", "1088x1920"),
        ("1024x1024", "1024x1024"),
        ("1152x1536", "1152x1536"),
        ("3840x2160", "3840x2160"),   # 上游示例里的合法尺寸原样保留
        ("1280x720", "1280x720"),
    ],
)
def test_size_is_aligned_to_multiples_of_16(raw, expected):
    assert image2._normalize_image_size(raw) == expected


def test_aligned_size_respects_upstream_limits():
    for raw in ("4096x4096", "512x512", "1920x1187", "5000x1000"):
        width, height = (int(v) for v in image2._normalize_image_size(raw).split("x"))
        assert width % 16 == 0 and height % 16 == 0
        assert max(width, height) <= 3840
        assert 655_360 <= width * height <= 8_294_400


def test_invalid_format_falls_back_to_a_valid_default():
    width, height = (int(v) for v in image2._normalize_image_size("auto-ish").split("x"))
    assert width % 16 == 0 and height % 16 == 0


def test_edit_payload_carries_the_aligned_size():
    assert image2._edit_payload("p", "1920x1080")["size"] == "1920x1088"
    assert image2._generation_payload("p", "1080x1920")["size"] == "1088x1920"
