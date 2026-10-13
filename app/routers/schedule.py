"""Thời khoá biểu cá nhân, chuông thông báo và kênh WebSocket thông báo."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db, utcnow
from ..deps import current_user
from ..models import Notification, StudyEvent, User
from ..schemas import EventIn, iso
from ..security import decode_token
from ..services.realtime import hub

router = APIRouter(tags=["Lịch học & thông báo"])


def next_remind(ev: StudyEvent, after: datetime) -> datetime | None:
    """Mốc nhắc kế tiếp sau thời điểm `after` (tính cả lịch lặp hằng ngày/hằng tuần)."""
    if ev.done:
        return None
    t = ev.start_at - timedelta(minutes=ev.remind_minutes)
    step = {"DAILY": timedelta(days=1), "WEEKLY": timedelta(days=7)}.get(ev.repeat)
    if t > after:
        return t
    if after < ev.start_at:          # đã qua giờ nhắc nhưng chưa tới giờ bắt đầu: nhắc ngay
        return after
    if not step:
        return None
    k = int((after - t) / step) + 1
    return t + k * step


def event_out(e: StudyEvent) -> dict:
    return {"id": e.id, "title": e.title, "note": e.note, "kind": e.kind, "start_at": iso(e.start_at), "end_at": iso(e.end_at),
            "repeat": e.repeat, "remind_minutes": e.remind_minutes, "notify_inapp": e.notify_inapp, "notify_email": e.notify_email,
            "next_remind_at": iso(e.next_remind_at), "done": e.done}


@router.get("/api/events")
def list_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(StudyEvent).where(StudyEvent.user_id == user.id).order_by(StudyEvent.start_at)).all()
    return [event_out(e) for e in rows]


@router.post("/api/events", status_code=201)
def create_event(body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(StudyEvent).where(StudyEvent.user_id == user.id)) >= 500:
        raise HTTPException(400, "Tối đa 500 mục trong thời khoá biểu.")
    e = StudyEvent(user_id=user.id, **body.model_dump())
    e.next_remind_at = next_remind(e, utcnow())
    db.add(e)
    db.commit()
    return event_out(e)


@router.put("/api/events/{eid}")
def edit_event(eid: int, body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(StudyEvent, eid)
    if not e or e.user_id != user.id:
        raise HTTPException(404, "Không tìm thấy mục lịch.")
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    e.next_remind_at = next_remind(e, utcnow())
    db.commit()
    return event_out(e)


@router.delete("/api/events/{eid}")
def delete_event(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(StudyEvent, eid)
    if not e or e.user_id != user.id:
        raise HTTPException(404, "Không tìm thấy mục lịch.")
    db.delete(e)
    db.commit()
    return {"ok": True}


def notif_out(n: Notification) -> dict:
    return {"id": n.id, "title": n.title, "body": n.body, "link": n.link, "is_read": n.is_read, "created_at": iso(n.created_at)}


@router.get("/api/notifications")
def notifications(unread: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread:
        q = q.where(Notification.is_read.is_(False))
    rows = db.scalars(q.order_by(Notification.id.desc()).limit(100)).all()
    cnt = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False)))
    return {"unread": cnt, "items": [notif_out(n) for n in rows]}


@router.post("/api/notifications/{nid}/read")
def read_one(nid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.id == nid, Notification.user_id == user.id).values(is_read=True))
    db.commit()
    return {"ok": True}


@router.post("/api/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(is_read=True))
    db.commit()
    return {"ok": True}


@router.websocket("/ws/notify")
async def ws_notify(ws: WebSocket, token: str = ""):
    uid = decode_token(token)
    with SessionLocal() as db:
        u = db.get(User, uid) if uid else None
    if not u or not u.is_active:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.add(ws, u.id)
    try:
        while True:
            await ws.receive_text()      # giữ kết nối; client gửi "ping" định kỳ
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws, u.id)
