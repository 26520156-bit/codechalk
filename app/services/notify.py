"""Tạo thông báo trong ứng dụng (chuông) và gửi email nếu cần."""
from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from ..models import Notification, User
from ..schemas import iso
from . import mailer
from .realtime import hub


def notify(db: Session, user: User, title: str, body: str = "", link: str = "", email: bool = False, commit: bool = True) -> Notification:
    n = Notification(user_id=user.id, title=title[:200], body=body, link=link)
    db.add(n)
    if commit:
        db.commit()
    else:
        db.flush()
    hub.push_user(user.id, {"type": "notification", "item": {"id": n.id, "title": n.title, "body": n.body, "link": n.link,
                                                             "is_read": False, "created_at": iso(n.created_at)}})
    if email and user.email:
        threading.Thread(target=mailer.send, args=(user.email, title, body, link), daemon=True).start()
    return n
