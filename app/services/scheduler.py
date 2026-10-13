"""Vòng hẹn giờ chạy nền: chốt phòng thi, gửi nhắc lịch học (chuông + Gmail)."""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import StudyEvent, User
from ..schemas import vn_time
from . import mailer
from .contests import finalize_due
from .notify import notify

log = logging.getLogger("codechalk.scheduler")


def send_due_reminders() -> int:
    from ..routers.schedule import next_remind
    now = utcnow()
    sent = 0
    with SessionLocal() as db:
        due = db.scalars(select(StudyEvent).where(StudyEvent.next_remind_at.is_not(None), StudyEvent.next_remind_at <= now)).all()
        for ev in due:
            user = db.get(User, ev.user_id)
            if user and user.is_active and not ev.done and (ev.notify_inapp or ev.notify_email):
                occ = ev.next_remind_at + timedelta(minutes=ev.remind_minutes)
                label = {"STUDY": "Lịch học", "PRACTICE": "Lịch luyện code", "GOAL": "Mục tiêu", "EXAM": "Lịch thi"}.get(ev.kind, "Lịch")
                body = f"{label}: {ev.title}\nBắt đầu lúc {vn_time(occ)}." + (f"\n{ev.note}" if ev.note else "")
                if ev.notify_inapp:
                    notify(db, user, f"Nhắc lịch: {ev.title}", body, "/#lich-hoc", email=ev.notify_email)
                elif ev.notify_email:
                    threading.Thread(target=mailer.send, args=(user.email, f"Nhắc lịch: {ev.title}", body, "/#lich-hoc"), daemon=True).start()
                sent += 1
            ev.next_remind_at = next_remind(ev, now)
        db.commit()
    return sent


def tick() -> None:
    with SessionLocal() as db:
        finalize_due(db)
    send_due_reminders()


async def loop() -> None:
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            log.exception("scheduler tick lỗi")
        await asyncio.sleep(settings.scheduler_seconds)
