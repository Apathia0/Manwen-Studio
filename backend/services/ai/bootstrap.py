from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from models import AiChannel, AiModel, AiModelPrice, PlatformSetting, PointsProduct
from services.ai.crypto_secrets import encrypt_secret, last_four, read_platform_setting_payload


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
            "default_price": {"billing_type": "per_call", "price_config_json": {"points_per_call": 2}},
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
