from decimal import Decimal

from services.points.pricing import estimate_points, quantize_points, reserve_points_from_estimate
from services.ai.crypto_secrets import decrypt_secret, encrypt_secret, last_four, mask_secret


def test_estimate_per_call():
    pts = estimate_points(billing_type="per_call", price_config={"points_per_call": 3})
    assert pts == Decimal("3.0000")


def test_estimate_per_1k_tokens():
    pts = estimate_points(
        billing_type="per_1k_tokens",
        price_config={
            "input_points_per_1k": 1,
            "output_points_per_1k": 2,
            "min_points_per_call": 0.5,
        },
        input_tokens=1000,
        output_tokens=500,
        use_estimate_defaults=False,
    )
    assert pts == Decimal("2.0000")


def test_estimate_per_image():
    pts = estimate_points(
        billing_type="per_image",
        price_config={"points_per_image": 5},
        image_count=3,
    )
    assert pts == Decimal("15.0000")


def test_reserve_factor():
    est = Decimal("10.0000")
    reserved = reserve_points_from_estimate(est, Decimal("1.2"))
    assert reserved == Decimal("12.0000")


def test_encrypt_roundtrip():
    secret = "unit-test-secret-key"
    plain = "sk-test-abcdef123456"
    cipher = encrypt_secret(plain, secret=secret)
    assert cipher != plain
    assert decrypt_secret(cipher, secret=secret) == plain
    assert last_four(plain) == "3456"
    assert mask_secret(plain).endswith("3456")


def test_quantize():
    assert quantize_points(Decimal("1.23456")) == Decimal("1.2346")


def test_estimate_per_second_custom_duration():
    pts = estimate_points(
        billing_type="per_second",
        price_config={"points_per_second": 3, "estimate_default_seconds": 15},
        video_seconds=20,
        use_estimate_defaults=False,
    )
    assert pts == Decimal("60.0000")


def test_estimate_per_second_default_when_missing():
    pts = estimate_points(
        billing_type="per_second",
        price_config={"points_per_second": 2, "estimate_default_seconds": 12},
        video_seconds=0,
        use_estimate_defaults=True,
    )
    assert pts == Decimal("24.0000")
