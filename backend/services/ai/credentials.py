from __future__ import annotations

import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import UserAiCredential, UserAiModalityCredential
from services.ai.crypto_secrets import decrypt_secret, encrypt_secret, last_four


def get_credential_row(db: Session, user_id: int) -> UserAiCredential | None:
    return db.query(UserAiCredential).filter(UserAiCredential.user_id == user_id).first()


MODALITIES = ("text", "image", "video")


def normalize_modality(modality: str) -> str:
    value = (modality or "").strip().lower()
    if value not in MODALITIES:
        raise HTTPException(400, "modality 只能是 text、image 或 video")
    return value


def get_modality_credential_row(db: Session, user_id: int, modality: str) -> UserAiModalityCredential | None:
    value = normalize_modality(modality)
    return db.query(UserAiModalityCredential).filter(
        UserAiModalityCredential.user_id == user_id,
        UserAiModalityCredential.modality == value,
    ).first()


def serialize_credential(row: UserAiCredential | None) -> dict[str, Any]:
    if not row or row.status == "empty" or not row.secret_ciphertext:
        return {
            "configured": False,
            "status": "empty",
            "last_four": None,
            "last_validated_at": None,
        }
    return {
        "configured": True,
        "status": row.status,
        "last_four": row.last_four,
        "last_validated_at": row.last_validated_at.isoformat() if row.last_validated_at else None,
    }


def serialize_modality_credential(row: UserAiModalityCredential | None, modality: str) -> dict[str, Any]:
    return {"modality": normalize_modality(modality), **serialize_credential(row)}


def serialize_modality_credentials(db: Session, user_id: int) -> dict[str, Any]:
    has_modality_slots = db.query(UserAiModalityCredential.id).filter(
        UserAiModalityCredential.user_id == user_id
    ).first()
    if not has_modality_slots:
        legacy = serialize_credential(get_credential_row(db, user_id))
        credentials = {
            modality: {"modality": modality, **legacy}
            for modality in MODALITIES
        }
        return {
            "credentials": credentials,
            "configured_count": len(MODALITIES) if legacy["configured"] else 0,
        }
    credentials = {
        modality: serialize_modality_credential(get_modality_credential_row(db, user_id, modality), modality)
        for modality in MODALITIES
    }
    return {
        "credentials": credentials,
        "configured_count": sum(1 for item in credentials.values() if item["configured"]),
    }


def materialize_modality_credentials(db: Session, user_id: int) -> None:
    has_modality_slots = db.query(UserAiModalityCredential.id).filter(
        UserAiModalityCredential.user_id == user_id
    ).first()
    if has_modality_slots:
        return
    legacy = get_credential_row(db, user_id)
    legacy_configured = bool(legacy and legacy.secret_ciphertext and legacy.status != "empty")
    for modality in MODALITIES:
        db.add(UserAiModalityCredential(
            user_id=user_id,
            modality=modality,
            secret_ciphertext=legacy.secret_ciphertext if legacy_configured else None,
            key_version=int(legacy.key_version or 1) if legacy_configured else 1,
            last_four=legacy.last_four if legacy_configured else None,
            status=legacy.status if legacy_configured else "empty",
            last_validated_at=legacy.last_validated_at if legacy_configured else None,
            updated_at=(legacy.updated_at or datetime.datetime.utcnow()) if legacy_configured else datetime.datetime.utcnow(),
        ))
    db.flush()


def save_user_api_key(db: Session, user_id: int, api_key: str) -> UserAiCredential:
    plain = (api_key or "").strip()
    if not plain:
        raise HTTPException(400, "API Key 不能为空")
    row = get_credential_row(db, user_id)
    if not row:
        row = UserAiCredential(user_id=user_id)
        db.add(row)
    row.secret_ciphertext = encrypt_secret(plain)
    row.last_four = last_four(plain)
    row.status = "active"
    row.key_version = int(row.key_version or 1)
    row.updated_at = datetime.datetime.utcnow()
    db.flush()
    return row


def save_user_modality_api_key(
    db: Session, user_id: int, modality: str, api_key: str, *, sync_legacy: bool = True
) -> UserAiModalityCredential:
    value = normalize_modality(modality)
    plain = (api_key or "").strip()
    if not plain:
        raise HTTPException(400, "API Key 不能为空")
    materialize_modality_credentials(db, user_id)
    row = get_modality_credential_row(db, user_id, value)
    if not row:
        raise RuntimeError(f"未能初始化 {value} API Key 槽位")
    row.secret_ciphertext = encrypt_secret(plain)
    row.last_four = last_four(plain)
    row.status = "active"
    row.key_version = int(row.key_version or 1)
    row.updated_at = datetime.datetime.utcnow()
    if value == "text" and sync_legacy:
        save_user_api_key(db, user_id, plain)
    db.flush()
    return row


def save_shared_api_key_to_all_modalities(db: Session, user_id: int, api_key: str) -> UserAiCredential:
    legacy = save_user_api_key(db, user_id, api_key)
    for modality in MODALITIES:
        save_user_modality_api_key(db, user_id, modality, api_key, sync_legacy=False)
    return legacy


def clear_user_api_key(db: Session, user_id: int) -> None:
    row = get_credential_row(db, user_id)
    if not row:
        return
    row.secret_ciphertext = None
    row.last_four = None
    row.status = "empty"
    row.updated_at = datetime.datetime.utcnow()
    db.flush()


def clear_user_modality_api_key(db: Session, user_id: int, modality: str, *, sync_legacy: bool = True) -> None:
    value = normalize_modality(modality)
    materialize_modality_credentials(db, user_id)
    row = get_modality_credential_row(db, user_id, value)
    if not row:
        raise RuntimeError(f"未能初始化 {value} API Key 槽位")
    row.secret_ciphertext = None
    row.last_four = None
    row.status = "empty"
    row.last_validated_at = None
    row.updated_at = datetime.datetime.utcnow()
    if value == "text" and sync_legacy:
        clear_user_api_key(db, user_id)
    db.flush()


def clear_all_user_api_keys(db: Session, user_id: int) -> None:
    clear_user_api_key(db, user_id)
    for modality in MODALITIES:
        clear_user_modality_api_key(db, user_id, modality, sync_legacy=False)


def load_user_api_key_plain(db: Session, user_id: int, modality: str | None = None) -> str | None:
    if modality is not None:
        row = get_modality_credential_row(db, user_id, modality)
        if row is not None:
            if not row.secret_ciphertext or row.status == "empty":
                return None
            try:
                return decrypt_secret(row.secret_ciphertext)
            except Exception:
                row.status = "invalid"
                db.flush()
                return None
        has_modality_slots = db.query(UserAiModalityCredential.id).filter(
            UserAiModalityCredential.user_id == user_id
        ).first()
        if has_modality_slots:
            return None
    row = get_credential_row(db, user_id)
    if not row or not row.secret_ciphertext or row.status == "empty":
        return None
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception:
        row.status = "invalid"
        db.flush()
        return None


def mark_credential_validated(db: Session, user_id: int, ok: bool) -> None:
    row = get_credential_row(db, user_id)
    if not row:
        return
    row.status = "active" if ok else "invalid"
    row.last_validated_at = datetime.datetime.utcnow()
    db.flush()


def mark_modality_credential_validated(db: Session, user_id: int, modality: str, ok: bool) -> None:
    row = get_modality_credential_row(db, user_id, modality)
    if not row:
        return
    row.status = "active" if ok else "invalid"
    row.last_validated_at = datetime.datetime.utcnow()
    db.flush()
