from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from models import AiChannel, AiModel, AiModelPrice, PlatformSetting, PointsProduct
from services.ai.crypto_secrets import encrypt_secret, last_four, read_platform_setting_payload
from services.points.pricing import (
    DEFAULT_TEXT_INPUT_TOKENS,
    DEFAULT_TEXT_MIN_POINTS,
    DEFAULT_TEXT_OUTPUT_TOKENS,
)


def _text_price_config(
    input_points_per_1m: Decimal | int | float,
    output_points_per_1m: Decimal | int | float | None = None,
) -> dict[str, int | float]:
    output_rate = input_points_per_1m if output_points_per_1m is None else output_points_per_1m
    return {
        "input_points_per_1m": float(input_points_per_1m),
        "output_points_per_1m": float(output_rate),
        "estimate_default_input_tokens": DEFAULT_TEXT_INPUT_TOKENS,
        "estimate_default_output_tokens": DEFAULT_TEXT_OUTPUT_TOKENS,
        "reservation_max_input_tokens": DEFAULT_TEXT_INPUT_TOKENS,
        "reservation_max_output_tokens": DEFAULT_TEXT_OUTPUT_TOKENS,
        "min_points_per_call": float(DEFAULT_TEXT_MIN_POINTS),
    }


def migrate_active_text_per_call_prices(db: Session, *, now: datetime.datetime | None = None) -> int:
    """将历史文本价格按默认 Token 预算等价迁移为每百万 Token 价格。"""
    from services.ai.catalog import get_active_price

    migrated = 0
    migration_time = now or datetime.datetime.utcnow()
    models = db.query(AiModel).filter(AiModel.modality == "text").all()
    for model in models:
        # 锁定模型行，避免并发首次请求重复创建迁移价格。
        locked_model = db.query(AiModel).with_for_update().filter(AiModel.id == model.id).one()
        active = get_active_price(db, locked_model.id)
        if not active or active.billing_type not in {"per_call", "per_1k_tokens"}:
            continue
        cfg = active.price_config_json or {}
        if active.billing_type == "per_call":
            try:
                estimated_call_points = Decimal(str(cfg.get("points_per_call", 0)))
            except Exception:
                continue
            total_tokens = Decimal(DEFAULT_TEXT_INPUT_TOKENS + DEFAULT_TEXT_OUTPUT_TOKENS)
            input_points_per_1m = output_points_per_1m = (
                max(Decimal("0"), estimated_call_points) * Decimal(1_000_000) / total_tokens
            )
        else:
            try:
                input_rate = Decimal(str(cfg.get("input_points_per_1k", 0)))
                output_rate = Decimal(str(cfg.get("output_points_per_1k", 0)))
            except Exception:
                continue
            input_points_per_1m = max(Decimal("0"), input_rate) * Decimal(1000)
            output_points_per_1m = max(Decimal("0"), output_rate) * Decimal(1000)
        active.valid_to = migration_time
        db.add(
            AiModelPrice(
                model_id=locked_model.id,
                billing_type="per_1m_tokens",
                price_config_json=_text_price_config(input_points_per_1m, output_points_per_1m),
                valid_from=migration_time,
                created_by=active.created_by,
            )
        )
        migrated += 1
    return migrated


def _setting_value(db: Session, key: str) -> str:
    row = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if not row or row.value_json is None:
        return ""
    val = read_platform_setting_payload(row.value_json, "")
    return str(val or "").strip()


def ensure_default_channels_and_models(db: Session) -> None:
    specs = [
        {
            "code": "default_text",
            "name": "默认文本渠道",
            "modality": "text",
            "url_key": "api.deepseek.base_url",
            "key_key": "api.deepseek.api_key",
            "model_key": "api.deepseek.model",
            "default_price": {
                "billing_type": "per_1m_tokens",
                "price_config_json": _text_price_config(2000),
            },
        },
        {
            "code": "default_image",
            "name": "默认图片渠道",
            "modality": "image",
            "url_key": "api.image.base_url",
            "key_key": "api.image.api_key",
            "model_key": "api.image.model",
            "default_price": {"billing_type": "per_image", "price_config_json": {"points_per_image": 5}},
        },
        {
            "code": "default_video",
            "name": "默认视频渠道",
            "modality": "video",
            "url_key": "api.video.base_url",
            "key_key": "api.video.api_key",
            "model_key": "api.video.model",
            "default_price": {
                "billing_type": "per_second",
                "price_config_json": {
                    "points_per_second": 3,
                    "estimate_default_seconds": 15,
                },
            },
        },
    ]

    for spec in specs:
        ch = db.query(AiChannel).filter(AiChannel.code == spec["code"]).first()
        if not ch:
            base_url = _setting_value(db, spec["url_key"])
            api_key = _setting_value(db, spec["key_key"])
            ch = AiChannel(
                code=spec["code"],
                name=spec["name"],
                adapter_type="openai_compatible" if spec["modality"] != "video" else "lingdong_video",
                base_url=base_url,
                modality=spec["modality"],
                enabled=True,
            )
            if api_key:
                ch.platform_secret_ciphertext = encrypt_secret(api_key)
                ch.last_four = last_four(api_key)
            db.add(ch)
            db.flush()

        model_name = _setting_value(db, spec["model_key"]) or f"default-{spec['modality']}"
        model = (
            db.query(AiModel)
            .filter(AiModel.channel_id == ch.id, AiModel.model_key == model_name)
            .first()
        )
        if not model:
            model = AiModel(
                channel_id=ch.id,
                model_key=model_name,
                display_name=model_name,
                modality=spec["modality"],
                enabled=True,
                user_visible=True,
                sort_order=0,
            )
            db.add(model)
            db.flush()
            price = AiModelPrice(
                model_id=model.id,
                billing_type=spec["default_price"]["billing_type"],
                price_config_json=spec["default_price"]["price_config_json"],
                valid_from=datetime.datetime.utcnow(),
            )
            db.add(price)
        elif spec["modality"] == "video":
            from services.ai.catalog import get_active_price

            active = get_active_price(db, model.id)
            need_per_second = (
                active is None
                or (active.billing_type or "") != "per_second"
            )
            if need_per_second:
                now = datetime.datetime.utcnow()
                if active:
                    active.valid_to = now
                db.add(
                    AiModelPrice(
                        model_id=model.id,
                        billing_type="per_second",
                        price_config_json={
                            "points_per_second": 3,
                            "estimate_default_seconds": 15,
                        },
                        valid_from=now,
                    )
                )

        if spec["modality"] == "video" and not model.capabilities_json:
            model.capabilities_json = {
                "schema_version": 1,
                "video": {
                    "payload_profile": "legacy_lingdong",
                    "input_modes": ["text_to_video", "image_to_video"],
                    "limits": {
                        "aspect_ratios": ["16:9", "9:16"],
                        "resolutions": ["720P"],
                        "duration_seconds": {"allowed": [15]},
                        "max_reference_images": 9,
                    },
                    "wire": {
                        "duration_field": "duration",
                        "reference_field": "input_reference",
                    },
                },
            }

    migrate_active_text_per_call_prices(db)

    if db.query(PointsProduct).count() == 0:
        defaults = [
            ("pts_10", "体验积分包", "适合短篇体验与少量图片生成", "10.00", "100", "0", False),
            ("pts_50", "创作积分包", "适合持续创作，额外赠送 50 积分", "50.00", "550", "50", True),
            ("pts_100", "专业积分包", "适合长篇与视频创作，额外赠送 200 积分", "100.00", "1200", "200", False),
        ]
        for i, (code, name, description, price, pts, bonus, recommended) in enumerate(defaults):
            db.add(
                PointsProduct(
                    code=code,
                    name=name,
                    description=description,
                    price_cny=Decimal(price),
                    points=Decimal(pts),
                    bonus_points=Decimal(bonus),
                    is_visible=True,
                    is_recommended=recommended,
                    sort_order=i,
                )
            )
    db.commit()
