from __future__ import annotations

import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import UserAiCredential
from services.ai.crypto_secrets import decrypt_secret, encrypt_secret, last_four


def get_credential_row(db: Session, user_id: int) -> UserAiCredential | None:
    return db.query(UserAiCredential).filter(UserAiCredential.user_id == user_id).first()


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


def clear_user_api_key(db: Session, user_id: int) -> None:
    row = get_credential_row(db, user_id)
    if not row:
        return
    row.secret_ciphertext = None
    row.last_four = None
    row.status = "empty"
    row.updated_at = datetime.datetime.utcnow()
    db.flush()


def load_user_api_key_plain(db: Session, user_id: int) -> str | None:
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
