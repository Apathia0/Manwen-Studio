import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import PointsAccount, PointsLedgerEntry
from routers import points_ai


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/points/ledger", "headers": []})


def _seed_ledger(db):
    account = PointsAccount(
        user_id=7,
        available_points=Decimal("100"),
        reserved_points=Decimal("0"),
    )
    db.add(account)
    db.flush()
    rows = [
        ("usage", "-1", "99", datetime.datetime(2026, 7, 1, 2, 0)),
        ("usage", "-2", "97", datetime.datetime(2026, 7, 2, 4, 0)),
        ("purchase", "10", "107", datetime.datetime(2026, 7, 2, 15, 59, 59)),
        ("usage", "-3", "104", datetime.datetime(2026, 7, 3, 1, 0)),
    ]
    for index, (entry_type, amount, balance, created_at) in enumerate(rows, start=1):
        db.add(PointsLedgerEntry(
            account_id=account.id,
            entry_type=entry_type,
            amount=Decimal(amount),
            balance_after=Decimal(balance),
            idempotency_key=f"ledger-test-{index}",
            created_at=created_at,
        ))
    db.commit()
    return account


def test_points_ledger_supports_pagination_and_combined_filters(monkeypatch):
    db = _session()
    account = _seed_ledger(db)
    monkeypatch.setattr(points_ai, "_require_user", lambda *_args: SimpleNamespace(id=account.user_id))

    second_page = points_ai.points_ledger(
        _request(),
        page=2,
        page_size=2,
        start_date=None,
        end_date=None,
        entry_type=None,
        direction=None,
        db=db,
    )
    assert second_page["total"] == 4
    assert second_page["total_pages"] == 2
    assert [item["amount"] for item in second_page["items"]] == [-2.0, -1.0]

    filtered = points_ai.points_ledger(
        _request(),
        page=1,
        page_size=20,
        start_date=datetime.date(2026, 7, 2),
        end_date=datetime.date(2026, 7, 2),
        entry_type="purchase",
        direction="income",
        db=db,
    )
    assert filtered["total"] == 1
    assert filtered["items"][0]["entry_type"] == "purchase"
    assert filtered["items"][0]["created_at"] == "2026-07-02T15:59:59+00:00"

    latest = points_ai.points_ledger(
        _request(),
        page=1,
        page_size=20,
        start_date=None,
        end_date=datetime.date.max,
        entry_type=None,
        direction=None,
        db=db,
    )
    assert latest["total"] == 4


def test_points_ledger_rejects_reversed_date_range(monkeypatch):
    db = _session()
    account = _seed_ledger(db)
    monkeypatch.setattr(points_ai, "_require_user", lambda *_args: SimpleNamespace(id=account.user_id))

    with pytest.raises(HTTPException) as exc_info:
        points_ai.points_ledger(
            _request(),
            page=1,
            page_size=20,
            start_date=datetime.date(2026, 7, 3),
            end_date=datetime.date(2026, 7, 2),
            entry_type=None,
            direction=None,
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "开始日期不能晚于结束日期"
