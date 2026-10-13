"""Gói dịch vụ, đơn thanh toán VietQR và xác nhận của HOST."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..deps import active_plans, current_user, require_host
from ..models import APPROVED, CANCELLED, PENDING, REJECTED, ROLE_HOST, PaymentOrder, Plan, User, UserPlan
from ..schemas import GrantIn, OrderIn, PlanIn, ReviewIn, iso, user_out, vn_time
from ..services import vietqr
from ..services.notify import notify

router = APIRouter(tags=["Gói & thanh toán"])


def plan_out(p: Plan) -> dict:
    return {"id": p.id, "name": p.name, "price_vnd": p.price_vnd, "duration_days": p.duration_days,
            "description": p.description, "features": p.features or [], "is_active": p.is_active}


def bank_info() -> dict:
    return {"bank_name": settings.bank_name, "bank_bin": settings.bank_bin, "account": settings.bank_account,
            "holder": settings.bank_holder}


def order_out(o: PaymentOrder, with_qr: bool = False) -> dict:
    d = {"id": o.id, "plan_id": o.plan_id, "plan_name": o.plan.name if o.plan else o.plan_id, "amount_vnd": o.amount_vnd,
         "transfer_code": o.transfer_code, "status": o.status, "note": o.note, "created_at": iso(o.created_at),
         "reviewed_at": iso(o.reviewed_at), "user": user_out(o.user, private=True) if o.user else None}
    if with_qr and o.status == PENDING and settings.bank_account:
        data = vietqr.payload(settings.bank_bin, settings.bank_account, o.amount_vnd, o.transfer_code)
        d["qr"] = {"payload": data, "image": vietqr.png_data_uri(data), **bank_info()}
    return d


@router.get("/api/plans")
def list_plans(db: Session = Depends(get_db)):
    return [plan_out(p) for p in db.scalars(select(Plan).order_by(Plan.sort_order)).all()]


@router.get("/api/plans/me")
def my_plans(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(UserPlan).where(UserPlan.user_id == user.id)).all()
    return {"active": sorted(active_plans(db, user)),
            "grants": [{"plan_id": r.plan_id, "starts_at": iso(r.starts_at), "expires_at": iso(r.expires_at)} for r in rows]}


@router.post("/api/payments/orders", status_code=201)
def create_order(body: OrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = db.get(Plan, body.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(404, "Gói không tồn tại.")
    if not settings.bank_account:
        raise HTTPException(503, "HOST chưa cấu hình tài khoản nhận tiền (BANK_ACCOUNT).")
    code = f"SUB_{user.id}_{plan.id}"
    o = db.scalar(select(PaymentOrder).where(PaymentOrder.user_id == user.id, PaymentOrder.plan_id == plan.id,
                                             PaymentOrder.status == PENDING))
    if o is None:
        o = PaymentOrder(user_id=user.id, plan_id=plan.id, amount_vnd=plan.price_vnd, transfer_code=code)
        db.add(o)
        db.commit()
        for h in db.scalars(select(User).where(User.role == ROLE_HOST)).all():
            notify(db, h, "Đơn đăng ký gói mới", f"{user.full_name or user.email} đăng ký gói {plan.name} "
                   f"({plan.price_vnd:,}đ). Nội dung chuyển khoản: {code}.".replace(",", "."), "/#admin-thanh-toan")
    return order_out(o, with_qr=True)


@router.get("/api/payments/orders")
def my_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(PaymentOrder).where(PaymentOrder.user_id == user.id).order_by(PaymentOrder.id.desc())).all()
    return [order_out(o, with_qr=True) for o in rows]


@router.post("/api/payments/orders/{oid}/cancel")
def cancel_order(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = db.get(PaymentOrder, oid)
    if not o or o.user_id != user.id:
        raise HTTPException(404, "Không tìm thấy đơn.")
    if o.status != PENDING:
        raise HTTPException(400, "Chỉ huỷ được đơn đang chờ duyệt.")
    o.status = CANCELLED
    db.commit()
    return order_out(o)


# ---------- HOST ----------
def grant_plan(db: Session, user: User, plan_id: str, days: int, by: User, order_id: int | None = None) -> UserPlan:
    now = utcnow()
    up = db.scalar(select(UserPlan).where(UserPlan.user_id == user.id, UserPlan.plan_id == plan_id))
    if up is None:
        up = UserPlan(user_id=user.id, plan_id=plan_id, starts_at=now)
        db.add(up)
    base = up.expires_at if up.expires_at and up.expires_at > now else now   # gia hạn cộng dồn
    up.expires_at = None if days == 0 else base + timedelta(days=days)
    up.granted_by, up.order_id = by.id, order_id
    return up


@router.get("/api/admin/payments")
def admin_orders(status: str = PENDING, host: User = Depends(require_host), db: Session = Depends(get_db)):
    q = select(PaymentOrder).order_by(PaymentOrder.id.desc())
    if status != "ALL":
        q = q.where(PaymentOrder.status == status)
    return [order_out(o) for o in db.scalars(q.limit(500)).all()]


@router.post("/api/admin/payments/{oid}/approve")
def approve(oid: int, body: ReviewIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    o = db.get(PaymentOrder, oid)
    if not o:
        raise HTTPException(404, "Không tìm thấy đơn.")
    if o.status != PENDING:
        raise HTTPException(400, f"Đơn đang ở trạng thái {o.status}, không duyệt lại được.")
    grant = grant_plan(db, o.user, o.plan_id, o.plan.duration_days, host, o.id)
    o.status, o.reviewed_by, o.reviewed_at, o.note = APPROVED, host.id, utcnow(), body.note
    db.commit()
    until = f" tới {vn_time(grant.expires_at, '%d/%m/%Y')}" if grant.expires_at else ""
    notify(db, o.user, f"Đã kích hoạt gói {o.plan.name}", f"HOST đã xác nhận thanh toán {o.amount_vnd:,}đ.".replace(",", ".") +
           f" Gói {o.plan.name} có hiệu lực{until}.", "/#tai-khoan", email=True)
    return order_out(o)


@router.post("/api/admin/payments/{oid}/reject")
def reject(oid: int, body: ReviewIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    o = db.get(PaymentOrder, oid)
    if not o or o.status != PENDING:
        raise HTTPException(400, "Chỉ từ chối được đơn đang chờ duyệt.")
    o.status, o.reviewed_by, o.reviewed_at, o.note = REJECTED, host.id, utcnow(), body.note
    db.commit()
    notify(db, o.user, f"Đơn gói {o.plan.name} chưa được duyệt", body.note or "HOST chưa nhận được khoản chuyển khoản khớp nội dung.",
           "/#tai-khoan", email=True)
    return order_out(o)


@router.post("/api/admin/users/{uid}/grant")
def grant(uid: int, body: GrantIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Không tìm thấy tài khoản.")
    grant_plan(db, u, body.plan_id, body.days, host)
    db.commit()
    plan = db.get(Plan, body.plan_id)
    notify(db, u, f"Bạn được cấp gói {plan.name if plan else body.plan_id}", "Quyền đã được HOST cấp trực tiếp.", "/#tai-khoan")
    return {"ok": True, "plans": sorted(active_plans(db, u))}


@router.patch("/api/admin/plans/{pid}")
def edit_plan(pid: str, body: PlanIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    p = db.get(Plan, pid)
    if not p:
        raise HTTPException(404, "Không tìm thấy gói.")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return plan_out(p)
