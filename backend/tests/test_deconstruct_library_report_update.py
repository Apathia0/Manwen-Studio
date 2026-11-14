"""
测试：PATCH /api/deconstruct/works/{work_id}/report 和
      PATCH /api/deconstruct/works/{work_id}/author-style/report

使用 SQLite 内存数据库 + monkeypatch 模拟用户认证。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from fastapi import HTTPException

from database import Base
from models import User, DeconstructionWork
from routers.deconstruct_library import (
    update_deconstruction_report,
    update_author_style_report,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def user(db_session: Session) -> User:
    u = User(
        id=1,
        email="test@example.com",
        name="测试用户",
        password_hash="hashed_pw",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def other_user(db_session: Session) -> User:
    u = User(
        id=2,
        email="other@example.com",
        name="其他用户",
        password_hash="hashed_pw",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def work(db_session: Session, user: User) -> DeconstructionWork:
    w = DeconstructionWork(
        owner_user_id=user.id,
        title="测试小说",
        author="测试作者",
        platform="manual",
        report_markdown="# 原始拆文报告\n原始内容。",
        decon_status="completed",
    )
    db_session.add(w)
    db_session.commit()
    db_session.refresh(w)
    return w


class _MockRequest:
    def __init__(self, json_data: dict):
        self._json_data = json_data

    async def json(self):
        return self._json_data


class TestUpdateDeconstructionReport:

    @pytest.mark.asyncio
    async def test_updates_report_successfully(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"report_markdown": "# 更新后的拆文报告\n新内容。"})

        result = await update_deconstruction_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] == "# 更新后的拆文报告\n新内容。"
        db_session.refresh(work)
        assert work.report_markdown == "# 更新后的拆文报告\n新内容。"

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_work(self, db_session, user, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"report_markdown": "内容"})

        with pytest.raises(HTTPException) as exc:
            await update_deconstruction_report(99999, request, db_session)

        assert exc.value.status_code == 404
        assert "拆书工作不存在" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_returns_404_for_other_users_work(self, db_session, work, other_user, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: other_user,
        )
        request = _MockRequest({"report_markdown": "内容"})

        with pytest.raises(HTTPException) as exc:
            await update_deconstruction_report(work.id, request, db_session)

        assert exc.value.status_code == 404
        assert "拆书工作不存在" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_does_not_update_when_report_markdown_is_null(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        original_value = work.report_markdown
        request = _MockRequest({"report_markdown": None})

        result = await update_deconstruction_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] == original_value
        db_session.refresh(work)
        assert work.report_markdown == original_value

    @pytest.mark.asyncio
    async def test_returns_current_value_when_field_absent(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"other_field": "value"})

        result = await update_deconstruction_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] == work.report_markdown

    @pytest.mark.asyncio
    async def test_clears_report_with_empty_string(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"report_markdown": ""})

        result = await update_deconstruction_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] == ""
        db_session.refresh(work)
        assert work.report_markdown == ""

    def test_route_registered(self):
        from routers.deconstruct_library import router
        patch_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "PATCH" in r.methods
            and r.path == "/api/deconstruct/works/{work_id}/report"
        ]
        assert len(patch_routes) == 1
        assert patch_routes[0].endpoint.__name__ == "update_deconstruction_report"


class TestUpdateAuthorStyleReport:

    @pytest.mark.asyncio
    async def test_updates_author_style_report_successfully(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        new_content = "# 作者风格画像报告\n新分析结果。"
        request = _MockRequest({"report_markdown": new_content})

        result = await update_author_style_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] == new_content
        db_session.refresh(work)
        assert work.author_style_report_markdown == new_content

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_work(self, db_session, user, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"report_markdown": "内容"})

        with pytest.raises(HTTPException) as exc:
            await update_author_style_report(99999, request, db_session)

        assert exc.value.status_code == 404
        assert "拆书工作不存在" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_returns_404_for_other_users_work(self, db_session, work, other_user, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: other_user,
        )
        request = _MockRequest({"report_markdown": "内容"})

        with pytest.raises(HTTPException) as exc:
            await update_author_style_report(work.id, request, db_session)

        assert exc.value.status_code == 404
        assert "拆书工作不存在" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_does_not_update_when_report_markdown_is_null(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"report_markdown": None})

        result = await update_author_style_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] is None
        db_session.refresh(work)
        assert work.author_style_report_markdown is None

    @pytest.mark.asyncio
    async def test_returns_current_value_when_field_absent(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"other_field": "value"})

        result = await update_author_style_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] is None

    @pytest.mark.asyncio
    async def test_clears_author_style_report_with_empty_string(self, db_session, user, work, monkeypatch):
        monkeypatch.setattr(
            "routers.deconstruct_library._require_user",
            lambda req, db: user,
        )
        request = _MockRequest({"report_markdown": ""})

        result = await update_author_style_report(work.id, request, db_session)

        assert result["ok"] is True
        assert result["report_markdown"] == ""
        db_session.refresh(work)
        assert work.author_style_report_markdown == ""

    def test_route_registered(self):
        from routers.deconstruct_library import router
        patch_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "PATCH" in r.methods
            and r.path == "/api/deconstruct/works/{work_id}/author-style/report"
        ]
        assert len(patch_routes) == 1
        assert patch_routes[0].endpoint.__name__ == "update_author_style_report"
