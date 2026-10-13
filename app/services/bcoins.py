"""Sổ cái Bcoins: mọi thay đổi số dư đều có một dòng giao dịch."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BcoinTransaction, User


def change(db: Session, user_id: int, amount: int, reason: str, ref_type: str = "", ref_id: int | None = None,
           note: str = "") -> BcoinTransaction:
    """Cộng (amount > 0) hoặc trừ (amount < 0). Khoá dòng người dùng để tránh trừ trùng khi bấm liên tục."""
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
    if user.bcoins + amount < 0:
        raise HTTPException(400, f"Số dư không đủ: bạn có {user.bcoins} Bcoins.")
    user.bcoins += amount
    tx = BcoinTransaction(user_id=user_id, amount=amount, balance_after=user.bcoins, reason=reason, ref_type=ref_type,
                          ref_id=ref_id, note=note[:255])
    db.add(tx)
    db.flush()
    return tx
