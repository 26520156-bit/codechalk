"""Shop đổi quà: đổi Bcoins thành tiền (100 Bcoins = 10.000đ), HOST xác nhận đã chuyển."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..deps import current_user, require_host
from ..models import COMPLETED, PENDING, REJECTED, ROLE_HOST, BcoinTransaction, CashoutRequest, User
from ..schemas import CashoutIn, ReviewIn, iso, user_out
from ..services import bcoins, storage
from ..services.notify import notify

router = APIRouter(tags=["Shop đổi quà"])


def vnd(bc: int) -> int:
    return bc * settings.bcoin_rate_vnd


def ticket_out(t: CashoutRequest, admin: bool = False) -> dict:
    d = {"id": t.id, "bcoins": t.bcoins, "amount_vnd": t.amount_vnd, "method": t.method, "bank_account": t.bank_account,
         "bank_name": t.bank_name, "account_holder": t.account_holder, "status": t.status, "note": t.note,
         "has_qr": bool(t.qr_image), "created_at": iso(t.created_at), "processed_at": iso(t.processed_at)}
    if admin:
        d["user"] = user_out(t.user, private=True)
    return d


@router.get("/api/shop/tiers")
def tiers():
    return [{"bcoins": b, "amount_vnd": vnd(b)} for b in range(100, 1001, 100)]


@router.get("/api/bcoins/me")
def my_bcoins(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tx = db.scalars(select(BcoinTransaction).where(BcoinTransaction.user_id == user.id).order_by(BcoinTransaction.id.desc()).limit(100)).all()
    return {"balance": user.bcoins, "transactions": [{"id": t.id, "amount": t.amount, "balance_after": t.balance_after,
                                                      "reason": t.reason, "note": t.note, "created_at": iso(t.created_at)} for t in tx]}


@router.get("/api/shop/requests")
def my_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(CashoutRequest).where(CashoutRequest.user_id == user.id).order_by(CashoutRequest.id.desc())).all()
    return [ticket_out(t) for t in rows]


@router.post("/api/shop/cashout", status_code=201)
async def cashout(bcoins_amount: int = Form(..., alias="bcoins"), method: str = Form(...), bank_account: str = Form(""),
                  bank_name: str = Form(""), account_holder: str = Form(""), qr_image: Optional[UploadFile] = File(None),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        body = CashoutIn(bcoins=bcoins_amount, method=method, bank_account=bank_account.strip(), bank_name=bank_name.strip(),
                         account_holder=account_holder.strip())
    except ValidationError as e:
        raise HTTPException(422, e.errors()[0]["msg"].replace("Value error, ", "")) from None
    if body.method == "BANK" and not (body.bank_account and body.bank_name and body.account_holder):
        raise HTTPException(400, "Nhập đủ Số tài khoản, Tên ngân hàng và Tên chủ tài khoản.")
    if body.method == "QR" and (qr_image is None or not qr_image.filename):
        raise HTTPException(400, "Tải lên ảnh mã QR ngân hàng của bạn.")
    if user.bcoins < body.bcoins:
        raise HTTPException(400, f"Số dư không đủ: bạn có {user.bcoins} Bcoins.")
    rel = ""
    if body.method == "QR":
        rel, *_ = await storage.save(qr_image, "cashout", storage.IMG_EXT)
    t = CashoutRequest(user_id=user.id, bcoins=body.bcoins, amount_vnd=vnd(body.bcoins), method=body.method, qr_image=rel,
                       bank_account=body.bank_account, bank_name=body.bank_name, account_holder=body.account_holder)
    db.add(t)
    db.flush()
    bcoins.change(db, user.id, -body.bcoins, "CASHOUT", "cashout", t.id, f"Yêu cầu đổi #{t.id}")
    db.commit()
    for h in db.scalars(select(User).where(User.role == ROLE_HOST)).all():
        notify(db, h, "Yêu cầu đổi thưởng mới", f"{user.full_name or user.email} đổi {body.bcoins} Bcoins = {vnd(body.bcoins):,}đ.".replace(",", "."),
               "/#admin-doi-thuong", email=True)
    return ticket_out(t)


@router.get("/api/shop/requests/{tid}/qr")
def ticket_qr(tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(CashoutRequest, tid)
    if not t or not t.qr_image or (t.user_id != user.id and user.role != ROLE_HOST):
        raise HTTPException(404, "Không có ảnh QR.")
    return FileResponse(storage.abs_path(t.qr_image), headers={"X-Content-Type-Options": "nosniff"})


@router.get("/api/admin/cashouts")
def admin_list(status: str = PENDING, host: User = Depends(require_host), db: Session = Depends(get_db)):
    q = select(CashoutRequest).order_by(CashoutRequest.id.desc()).limit(500)
    if status != "ALL":
        q = q.where(CashoutRequest.status == status)
    return [ticket_out(t, admin=True) for t in db.scalars(q).all()]


@router.post("/api/admin/cashouts/{tid}/complete")
def complete(tid: int, body: ReviewIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    t = db.scalar(select(CashoutRequest).where(CashoutRequest.id == tid).with_for_update())
    if not t or t.status != PENDING:
        raise HTTPException(400, "Chỉ xác nhận được yêu cầu đang chờ.")
    t.status, t.processed_by, t.processed_at, t.note = COMPLETED, host.id, utcnow(), body.note
    db.commit()
    notify(db, t.user, "Đã chuyển tiền đổi thưởng", f"HOST đã chuyển {t.amount_vnd:,}đ cho yêu cầu #{t.id}.".replace(",", "."),
           "/#shop", email=True)
    return ticket_out(t, admin=True)


@router.post("/api/admin/cashouts/{tid}/reject")
def reject(tid: int, body: ReviewIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    t = db.scalar(select(CashoutRequest).where(CashoutRequest.id == tid).with_for_update())
    if not t or t.status != PENDING:
        raise HTTPException(400, "Chỉ từ chối được yêu cầu đang chờ.")
    t.status, t.processed_by, t.processed_at, t.note = REJECTED, host.id, utcnow(), body.note
    bcoins.change(db, t.user_id, t.bcoins, "REFUND", "cashout", t.id, f"Hoàn lại yêu cầu #{t.id}")
    db.commit()
    notify(db, t.user, "Yêu cầu đổi thưởng bị từ chối", (body.note or "Thông tin nhận tiền chưa hợp lệ.") +
           f" Đã hoàn lại {t.bcoins} Bcoins.", "/#shop", email=True)
    return ticket_out(t, admin=True)
