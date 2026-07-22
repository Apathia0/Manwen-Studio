from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import PointsAccount, PointsLedgerEntry
from services.points.pricing import ZERO, quantize_points


def ensure_account(db: Session, user_id: int) -> PointsAccount:
    account = db.query(PointsAccount).filter(PointsAccount.user_id == user_id).first()
    if account:
        return account
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        # 首次并发扣费时只创建一行，避免两个请求同时插入账户。
        db.execute(
            insert(PointsAccount)
            .values(
                user_id=user_id,
                available_points=ZERO,
                reserved_points=ZERO,
                version=0,
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        db.flush()
        return db.query(PointsAccount).filter(PointsAccount.user_id == user_id).one()
    account = PointsAccount(
        user_id=user_id,
        available_points=ZERO,
        reserved_points=ZERO,
        version=0,
    )
    db.add(account)
    db.flush()
    return account


def get_account_for_update(db: Session, user_id: int) -> PointsAccount:
    account = (
        db.query(PointsAccount)
        .filter(PointsAccount.user_id == user_id)
        .with_for_update()
        .first()
    )
    if account:
        return account
    ensure_account(db, user_id)
    db.flush()
    return (
        db.query(PointsAccount)
        .filter(PointsAccount.user_id == user_id)
        .with_for_update()
        .one()
    )


def _ledger_exists(db: Session, idempotency_key: str) -> PointsLedgerEntry | None:
    return db.query(PointsLedgerEntry).filter(PointsLedgerEntry.idempotency_key == idempotency_key).first()


def _assert_reservation_ownership(
    db: Session,
    account: PointsAccount,
    *,
    reserved_amount: Decimal,
    reserve_idempotency_key: str | None,
    usage_event_id: int | None,
) -> PointsLedgerEntry:
    """校验本次操作确实拥有对应的预留流水，禁止跨事件挪用预留余额。"""
    reserve = _ledger_exists(db, reserve_idempotency_key) if reserve_idempotency_key else None
    if reserve is None and usage_event_id is not None:
        reserve = (
            db.query(PointsLedgerEntry)
            .filter(
                PointsLedgerEntry.account_id == account.id,
                PointsLedgerEntry.usage_event_id == usage_event_id,
                PointsLedgerEntry.entry_type == "reserve",
            )
            .order_by(PointsLedgerEntry.id.asc())
            .first()
        )
    if not reserve or reserve.entry_type != "reserve":
        raise RuntimeError(f"未找到计费事件的预留流水: {reserve_idempotency_key}")
    if reserve.account_id != account.id:
        raise RuntimeError("预留流水与积分账户不匹配")
    if usage_event_id is not None and reserve.usage_event_id != usage_event_id:
        raise RuntimeError("预留流水与用量事件不匹配")
    expected = quantize_points(reserved_amount)
    if quantize_points(abs(reserve.amount)) != expected:
        raise RuntimeError(
            f"预留金额不一致: 流水 {reserve.amount}，请求 {expected}"
        )
    return reserve


def _write_ledger(
    db: Session,
    *,
    account: PointsAccount,
    entry_type: str,
    amount: Decimal,
    idempotency_key: str,
    usage_event_id: int | None = None,
    order_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> PointsLedgerEntry:
    existing = _ledger_exists(db, idempotency_key)
    if existing:
        return existing
    entry = PointsLedgerEntry(
        account_id=account.id,
        entry_type=entry_type,
        amount=quantize_points(amount),
        balance_after=quantize_points(account.available_points),
        idempotency_key=idempotency_key,
        usage_event_id=usage_event_id,
        order_id=order_id,
        metadata_json=metadata,
    )
    db.add(entry)
    db.flush()
    return entry


def credit_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    *,
    entry_type: str,
    idempotency_key: str,
    order_id: int | None = None,
    usage_event_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> PointsAccount:
    amount = quantize_points(amount)
    if amount <= ZERO:
        raise HTTPException(400, "入账积分必须大于 0")
    account = get_account_for_update(db, user_id)
    if _ledger_exists(db, idempotency_key):
        return account
    account.available_points = quantize_points(account.available_points + amount)
    account.version = int(account.version or 0) + 1
    _write_ledger(
        db,
        account=account,
        entry_type=entry_type,
        amount=amount,
        idempotency_key=idempotency_key,
        usage_event_id=usage_event_id,
        order_id=order_id,
        metadata=metadata,
    )
    return account


def reserve_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    *,
    idempotency_key: str,
    usage_event_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> PointsAccount:
    amount = quantize_points(amount)
    if amount <= ZERO:
        raise HTTPException(400, "预扣积分必须大于 0")
    account = get_account_for_update(db, user_id)
    if _ledger_exists(db, idempotency_key):
        return account
    if account.available_points < amount:
        raise HTTPException(
            402,
            f"积分不足：可用 {quantize_points(account.available_points)}，需要 {amount}",
        )
    account.available_points = quantize_points(account.available_points - amount)
    account.reserved_points = quantize_points(account.reserved_points + amount)
    account.version = int(account.version or 0) + 1
    _write_ledger(
        db,
        account=account,
        entry_type="reserve",
        amount=-amount,
        idempotency_key=idempotency_key,
        usage_event_id=usage_event_id,
        metadata=metadata,
    )
    return account


def charge_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    *,
    idempotency_key: str,
    usage_event_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Decimal:
    """直接从可用积分扣除增量金额，供流式 Token 计费使用。"""
    amount = quantize_points(max(ZERO, amount))
    if amount <= ZERO:
        return ZERO
    account = get_account_for_update(db, user_id)
    existing = _ledger_exists(db, idempotency_key)
    if existing:
        return quantize_points(abs(existing.amount))
    if account.available_points < amount:
        raise HTTPException(402, "积分不足，流式生成已停止")
    charged = amount
    account.available_points = quantize_points(account.available_points - charged)
    account.version = int(account.version or 0) + 1
    _write_ledger(
        db,
        account=account,
        entry_type="usage",
        amount=-charged,
        idempotency_key=idempotency_key,
        usage_event_id=usage_event_id,
        metadata={**(metadata or {}), "requested": str(amount), "charged": str(charged)},
    )
    return charged


def settle_reservation(
    db: Session,
    user_id: int,
    *,
    reserved_amount: Decimal,
    actual_amount: Decimal,
    reserve_idempotency_key: str,
    settle_idempotency_key: str,
    release_idempotency_key: str,
    usage_event_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Decimal:
    reserved_amount = quantize_points(reserved_amount)
    actual_amount = quantize_points(max(ZERO, actual_amount))

    account = get_account_for_update(db, user_id)
    existing_settlement = _ledger_exists(db, settle_idempotency_key)
    if existing_settlement:
        if existing_settlement.account_id != account.id:
            raise RuntimeError("结算幂等流水与积分账户不匹配")
        if usage_event_id is not None and existing_settlement.usage_event_id != usage_event_id:
            raise RuntimeError("结算幂等流水与用量事件不匹配")
        metadata_json = existing_settlement.metadata_json if isinstance(existing_settlement.metadata_json, dict) else {}
        charged = metadata_json.get("charged")
        if charged is not None:
            return quantize_points(Decimal(str(charged)))
        return quantize_points(reserved_amount + abs(existing_settlement.amount))

    _assert_reservation_ownership(
        db,
        account,
        reserved_amount=reserved_amount,
        reserve_idempotency_key=reserve_idempotency_key,
        usage_event_id=usage_event_id,
    )
    if account.reserved_points < reserved_amount:
        raise RuntimeError(
            f"积分预留不一致：账户预留 {account.reserved_points}，请求预留 {reserved_amount}"
        )

    charged_amount = min(
        actual_amount,
        quantize_points(reserved_amount + account.available_points),
    )
    release = quantize_points(reserved_amount - charged_amount)
    extra_charge = ZERO
    if release < ZERO:
        extra_charge = quantize_points(-release)
        release = ZERO

    account.reserved_points = quantize_points(account.reserved_points - reserved_amount)
    if extra_charge > ZERO:
        # 实际用量可能超过安全预留，优先从可用余额补扣。
        account.available_points = quantize_points(account.available_points - extra_charge)
    if release > ZERO:
        account.available_points = quantize_points(account.available_points + release)
    account.version = int(account.version or 0) + 1

    _write_ledger(
        db,
        account=account,
        entry_type="settle",
        # 预留流水已经记录了可用余额减少；结算只记录超出预留的补扣。
        amount=-extra_charge,
        idempotency_key=settle_idempotency_key,
        usage_event_id=usage_event_id,
        metadata={
            **(metadata or {}),
            "reserved": str(reserved_amount),
            "actual": str(actual_amount),
            "charged": str(charged_amount),
            "shortfall": str(quantize_points(actual_amount - charged_amount)),
        },
    )
    if release > ZERO:
        _write_ledger(
            db,
            account=account,
            entry_type="release",
            amount=release,
            idempotency_key=release_idempotency_key,
            usage_event_id=usage_event_id,
            metadata={**(metadata or {}), "released": str(release)},
        )
    return charged_amount


def release_reservation(
    db: Session,
    user_id: int,
    amount: Decimal,
    *,
    idempotency_key: str,
    reserve_idempotency_key: str | None = None,
    usage_event_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> PointsAccount:
    amount = quantize_points(amount)
    account = get_account_for_update(db, user_id)
    existing_release = _ledger_exists(db, idempotency_key)
    if existing_release:
        if existing_release.account_id != account.id:
            raise RuntimeError("释放幂等流水与积分账户不匹配")
        if usage_event_id is not None and existing_release.usage_event_id != usage_event_id:
            raise RuntimeError("释放幂等流水与用量事件不匹配")
        return account
    if amount <= ZERO:
        return account
    _assert_reservation_ownership(
        db,
        account,
        reserved_amount=amount,
        reserve_idempotency_key=reserve_idempotency_key,
        usage_event_id=usage_event_id,
    )
    if account.reserved_points < amount:
        raise RuntimeError(
            f"积分预留不足以释放: 账户预留 {account.reserved_points}，请求释放 {amount}"
        )
    release = amount
    account.reserved_points = quantize_points(account.reserved_points - release)
    account.available_points = quantize_points(account.available_points + release)
    account.version = int(account.version or 0) + 1
    _write_ledger(
        db,
        account=account,
        entry_type="release",
        amount=release,
        idempotency_key=idempotency_key,
        usage_event_id=usage_event_id,
        metadata=metadata,
    )
    return account


def serialize_account(account: PointsAccount) -> dict[str, Any]:
    return {
        "user_id": account.user_id,
        "available_points": float(quantize_points(account.available_points or ZERO)),
        "reserved_points": float(quantize_points(account.reserved_points or ZERO)),
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }
