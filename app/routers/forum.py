"""Forum: nhóm cộng đồng và phòng chat theo chủ đề, nhắn tin thời gian thực qua WebSocket."""
from __future__ import annotations

import json
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..deps import current_user
from ..models import ROLE_HOST, ChatRoom, Message, RoomMember, User
from ..schemas import iso, user_out
from ..security import decode_token
from ..services import storage
from ..services.realtime import hub

router = APIRouter(tags=["Forum"])


def member(db: Session, room_id: int, user_id: int) -> RoomMember | None:
    return db.scalar(select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user_id))


def room_out(db: Session, r: ChatRoom, me: User | None) -> dict:
    n = db.scalar(select(func.count()).select_from(RoomMember).where(RoomMember.room_id == r.id))
    last = db.scalar(select(Message).where(Message.room_id == r.id).order_by(Message.id.desc()).limit(1))
    m = member(db, r.id, me.id) if me else None
    unread = 0
    if m:
        unread = db.scalar(select(func.count()).select_from(Message).where(Message.room_id == r.id, Message.id > m.last_read_id,
                                                                            Message.user_id != me.id)) or 0
    return {"id": r.id, "name": r.name, "description": r.description, "kind": r.kind, "has_avatar": bool(r.avatar),
            "members": n, "online": len(hub.online_in_room(r.id)), "joined": m is not None, "is_owner": bool(m and m.role == "OWNER"),
            "unread": unread, "created_at": iso(r.created_at),
            "last": {"user": last.user.full_name or last.user.email.split("@")[0], "text": (last.content or ("Tệp: " + last.attachment_name))[:80],
                     "at": iso(last.created_at)} if last else None}


def msg_out(m: Message) -> dict:
    return {"id": m.id, "room_id": m.room_id, "user": user_out(m.user), "content": m.content, "created_at": iso(m.created_at),
            "attachment": {"name": m.attachment_name, "mime": m.attachment_mime, "is_image": m.attachment_mime.startswith("image/")}
            if m.attachment else None}


@router.get("/api/rooms")
def list_rooms(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(ChatRoom).order_by(ChatRoom.id.desc()).limit(300)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(ChatRoom.name).like(like), func.lower(ChatRoom.description).like(like)))
    return [room_out(db, r, user) for r in db.scalars(stmt).all()]


@router.post("/api/rooms", status_code=201)
async def create_room(name: str = Form(...), description: str = Form(""), kind: str = Form("ROOM"),
                      avatar: Optional[UploadFile] = File(None), user: User = Depends(current_user), db: Session = Depends(get_db)):
    name = name.strip()
    if not 2 <= len(name) <= 120:
        raise HTTPException(400, "Tên phòng từ 2 đến 120 ký tự.")
    if kind not in ("ROOM", "GROUP"):
        kind = "ROOM"
    rel = ""
    if avatar is not None and avatar.filename:
        rel, *_ = await storage.save(avatar, "rooms", storage.IMG_EXT)
    r = ChatRoom(name=name, description=description[:2000], kind=kind, avatar=rel, creator_id=user.id)
    db.add(r)
    db.flush()
    db.add(RoomMember(room_id=r.id, user_id=user.id, role="OWNER"))
    db.commit()
    return room_out(db, r, user)


def _room(db: Session, rid: int) -> ChatRoom:
    r = db.get(ChatRoom, rid)
    if not r:
        raise HTTPException(404, "Không tìm thấy phòng.")
    return r


@router.get("/api/rooms/{rid}")
def get_room(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _room(db, rid)
    d = room_out(db, r, user)
    online = set(hub.online_in_room(r.id))
    mem = db.scalars(select(RoomMember).where(RoomMember.room_id == r.id).order_by(RoomMember.joined_at)).all()
    d["member_list"] = [{**user_out(m.user), "online": m.user_id in online, "role": m.role, "last_read_id": m.last_read_id} for m in mem]
    return d


@router.get("/api/rooms/{rid}/avatar")
def room_avatar(rid: int, db: Session = Depends(get_db)):
    r = _room(db, rid)
    if not r.avatar:
        raise HTTPException(404, "Phòng chưa có ảnh.")
    return FileResponse(storage.abs_path(r.avatar), headers={"Cache-Control": "max-age=3600"})


@router.post("/api/rooms/{rid}/join")
def join_room(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _room(db, rid)
    if not member(db, r.id, user.id):
        db.add(RoomMember(room_id=r.id, user_id=user.id))
        db.commit()
        hub.push_room(r.id, {"type": "member", "action": "join", "user": user_out(user)})
    return room_out(db, r, user)


@router.post("/api/rooms/{rid}/leave")
def leave_room(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = member(db, rid, user.id)
    if m:
        db.delete(m)
        db.commit()
        hub.push_room(rid, {"type": "member", "action": "leave", "user": user_out(user)})
    return {"ok": True}


@router.delete("/api/rooms/{rid}")
def delete_room(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _room(db, rid)
    if r.creator_id != user.id and user.role != ROLE_HOST:
        raise HTTPException(403, "Chỉ người tạo phòng hoặc HOST được xoá.")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/api/rooms/{rid}/messages")
def messages(rid: int, before_id: int = 0, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not member(db, rid, user.id):
        raise HTTPException(403, "Bấm JOIN để xem và nhắn tin trong phòng.")
    q = select(Message).where(Message.room_id == rid)
    if before_id:
        q = q.where(Message.id < before_id)
    rows = db.scalars(q.order_by(Message.id.desc()).limit(max(1, min(limit, 100)))).all()
    return [msg_out(m) for m in reversed(rows)]


def _post(db: Session, rid: int, user: User, content: str, att: tuple | None = None) -> dict:
    if not member(db, rid, user.id):
        raise HTTPException(403, "Bấm JOIN để nhắn tin trong phòng.")
    content = (content or "").strip()[:4000]
    if not content and not att:
        raise HTTPException(400, "Tin nhắn trống.")
    m = Message(room_id=rid, user_id=user.id, content=content)
    if att:
        m.attachment, m.attachment_name, m.attachment_mime = att
    db.add(m)
    db.flush()
    mem = member(db, rid, user.id)
    mem.last_read_id = m.id
    db.commit()
    db.refresh(m)
    data = msg_out(m)
    hub.push_room(rid, {"type": "message", "message": data})
    return data


@router.post("/api/rooms/{rid}/messages", status_code=201)
async def post_message(rid: int, content: str = Form(""), file: Optional[UploadFile] = File(None),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    _room(db, rid)
    if not member(db, rid, user.id):
        raise HTTPException(403, "Bấm JOIN để nhắn tin trong phòng.")
    att = None
    if file is not None and file.filename:
        rel, original, mime, _ = await storage.save(file, "chat", storage.DOC_EXT)
        att = (rel, original, mime)
    return _post(db, rid, user, content, att)


@router.get("/api/messages/{mid}/file")
def message_file(mid: int, inline: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Message, mid)
    if not m or not m.attachment or not member(db, m.room_id, user.id):
        raise HTTPException(404, "Không tìm thấy tệp.")
    image = m.attachment_mime.startswith("image/")
    disp = "inline" if (inline and image) else "attachment"
    return FileResponse(storage.abs_path(m.attachment), media_type=m.attachment_mime if image else "application/octet-stream",
                        headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(m.attachment_name)}",
                                 "X-Content-Type-Options": "nosniff"})


@router.post("/api/rooms/{rid}/read")
def mark_read(rid: int, last_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = member(db, rid, user.id)
    if m and last_id > m.last_read_id:
        m.last_read_id = last_id
        db.commit()
        hub.push_room(rid, {"type": "read", "user_id": user.id, "name": user.full_name or user.email.split("@")[0], "last_id": last_id})
    return {"ok": True}


@router.websocket("/ws/rooms/{rid}")
async def ws_room(ws: WebSocket, rid: int, token: str = ""):
    uid = decode_token(token)
    with SessionLocal() as db:
        u = db.get(User, uid) if uid else None
        ok = bool(u and u.is_active and member(db, rid, u.id))
    if not ok:
        await ws.close(code=4403)
        return
    await ws.accept()
    hub.add(ws, u.id, rid)
    await hub.to_room(rid, {"type": "presence", "online": hub.online_in_room(rid)})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            kind = data.get("type")
            if kind == "message":
                with SessionLocal() as db:
                    user = db.get(User, u.id)
                    try:
                        _post(db, rid, user, str(data.get("content", "")))
                    except HTTPException as e:
                        await ws.send_text(json.dumps({"type": "error", "message": e.detail}, ensure_ascii=False))
            elif kind == "typing":
                await hub.to_room(rid, {"type": "typing", "user_id": u.id, "name": u.full_name or u.email.split("@")[0]})
            elif kind == "read":
                with SessionLocal() as db:
                    m = member(db, rid, u.id)
                    last = int(data.get("last_id") or 0)
                    if m and last > m.last_read_id:
                        m.last_read_id = last
                        db.commit()
                        await hub.to_room(rid, {"type": "read", "user_id": u.id, "name": u.full_name or u.email.split("@")[0], "last_id": last})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws, u.id, rid)
        await hub.to_room(rid, {"type": "presence", "online": hub.online_in_room(rid)})
