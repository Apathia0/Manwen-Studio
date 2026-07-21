import datetime
from types import SimpleNamespace

import main
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import EmailVerificationCode, PlatformSetting, UserSession
from schemas import ChapterContentUpdate, ChatMessageIn


def test_password_hash_uses_salted_pbkdf2(monkeypatch):
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "100000")

    first = main._password_hash("production-password")
    second = main._password_hash("production-password")

    assert first.startswith("pbkdf2_sha256$100000$")
    assert first != second
    assert main._verify_password("production-password", first) is True
    assert main._verify_password("wrong-password", first) is False


def test_session_token_fingerprint_does_not_store_bearer_token():
    token = "lv_plain-session-token"
    fingerprint = main._session_token_fingerprint(token)

    assert fingerprint.startswith("sha256$")
    assert token not in fingerprint


def test_legacy_session_token_is_migrated_without_logging_user_out():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        raw_token = "lv_legacy-session-token"
        db.add(UserSession(user_id=1, token=raw_token))
        db.commit()

        assert main._hash_legacy_session_tokens(db) == 1
        db.commit()

        stored = db.query(UserSession).one()
        assert stored.token == main._session_token_fingerprint(raw_token)
        assert raw_token not in stored.token
        assert main._find_active_session(raw_token, db) is stored
    finally:
        db.close()
        engine.dispose()


def test_legacy_password_hash_is_verified_and_requires_upgrade():
    legacy = main.hashlib.sha256(b"legacy-password").hexdigest()

    assert main._verify_password("legacy-password", legacy) is True
    assert main._password_needs_rehash(legacy) is True


def test_session_expiration_uses_configured_ttl(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_DAYS", "30")
    session = UserSession(
        user_id=1,
        token="token",
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=31),
    )

    assert main._session_is_expired(session) is True


def test_invalid_security_environment_values_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "invalid")
    monkeypatch.setenv("SESSION_TTL_DAYS", "invalid")
    session = UserSession(
        user_id=1,
        token="token",
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=31),
    )

    assert main._password_hash_iterations() == 600_000
    assert main._session_is_expired(session) is True


def test_verification_code_is_consumed_after_five_failures():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        record = EmailVerificationCode(
            email="user@example.com",
            purpose="reset",
            code_hash=main._verification_code_hash("user@example.com", "reset", "123456"),
            expires_at=main._utcnow() + datetime.timedelta(minutes=10),
        )
        db.add(record)
        db.commit()

        for attempt in range(1, 6):
            with pytest.raises(HTTPException):
                main._consume_email_verification_code("user@example.com", "reset", "000000", db)
            db.refresh(record)
            assert record.attempt_count == attempt

        assert record.consumed_at is not None
    finally:
        db.close()
        engine.dispose()


def test_dummy_verification_code_uses_same_rate_limit(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    monkeypatch.setattr(
        main,
        "_auth_settings_snapshot",
        lambda _db: {"email_code_length": 6, "email_code_expire_minutes": 10},
    )
    monkeypatch.setattr(main, "_get_platform_setting", lambda *args, **kwargs: "StoryCanvas")
    try:
        result = main._issue_email_verification_code(
            "missing@example.com",
            "reset",
            db,
            deliver=False,
        )
        assert result["ok"] is True

        with pytest.raises(HTTPException) as exc_info:
            main._issue_email_verification_code(
                "missing@example.com",
                "reset",
                db,
                deliver=False,
            )
        assert exc_info.value.status_code == 429
    finally:
        db.close()
        engine.dispose()


def test_platform_secret_is_encrypted_and_admin_snapshot_is_masked(monkeypatch):
    monkeypatch.setenv("AI_CREDENTIAL_SECRET", "test-secret-material-that-is-long-enough")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        main._seed_platform_settings(db)
        main._set_platform_setting("api.deepseek.api_key", "sk-production-secret", db)
        db.commit()

        row = db.query(PlatformSetting).filter_by(setting_key="api.deepseek.api_key").one()
        assert "sk-production-secret" not in str(row.value_json)
        assert main._get_platform_setting("api.deepseek.api_key", db, "") == "sk-production-secret"
        from services.ai.bootstrap import _setting_value

        assert _setting_value(db, "api.deepseek.api_key") == "sk-production-secret"

        snapshot = main._admin_platform_settings_snapshot(db)
        assert snapshot["api"]["deepseek_api_key"] == ""
        assert snapshot["api"]["deepseek_api_key_configured"] is True
        assert snapshot["api"]["deepseek_api_key_last_four"] == "cret"
    finally:
        db.close()
        engine.dispose()


def test_production_credential_secret_has_no_fixed_fallback(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AI_CREDENTIAL_SECRET", raising=False)
    from services.ai.crypto_secrets import get_secret_key_material

    with pytest.raises(RuntimeError, match="AI_CREDENTIAL_SECRET"):
        get_secret_key_material()


@pytest.mark.asyncio
async def test_chapter_ai_and_write_endpoints_require_owner_check(monkeypatch):
    user = SimpleNamespace(id=7)
    checked_ids = []

    def reject_other_owner(chapter_id, current_user, db):
        checked_ids.append((chapter_id, current_user.id))
        raise HTTPException(404, "章节未找到")

    monkeypatch.setattr(main, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main, "_require_chapter_for_user", reject_other_owner)
    request = SimpleNamespace(json=lambda: None)

    calls = [
        main.chat(11, ChatMessageIn(content="测试"), request, object()),
        main.generate_novel_endpoint(12, request, object()),
        main.import_novel_endpoint(13, request, object()),
        main.update_chapter_content(14, ChapterContentUpdate(content="测试正文"), request, object()),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 404

    assert checked_ids == [(11, 7), (12, 7), (13, 7), (14, 7)]
