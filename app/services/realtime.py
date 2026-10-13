"""Kết nối WebSocket: chuông thông báo theo người dùng và phòng chat theo phòng."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger("codechalk.realtime")


class Hub:
    def __init__(self) -> None:
        self.users: dict[int, set[WebSocket]] = defaultdict(set)
        self.rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self.ws_user: dict[WebSocket, int] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self) -> None:
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

    def add(self, ws: WebSocket, user_id: int, room_id: int | None = None) -> None:
        self.ws_user[ws] = user_id
        (self.rooms[room_id] if room_id is not None else self.users[user_id]).add(ws)

    def remove(self, ws: WebSocket, user_id: int, room_id: int | None = None) -> None:
        self.ws_user.pop(ws, None)
        bucket = self.rooms.get(room_id) if room_id is not None else self.users.get(user_id)
        if bucket is not None:
            bucket.discard(ws)

    def online_in_room(self, room_id: int) -> list[int]:
        return sorted({self.ws_user[w] for w in self.rooms.get(room_id, set()) if w in self.ws_user})

    async def _send(self, targets: set[WebSocket], data: dict) -> None:
        text = json.dumps(data, ensure_ascii=False, default=str)
        for ws in list(targets):
            try:
                await ws.send_text(text)
            except Exception:  # kết nối đã đóng
                targets.discard(ws)

    async def to_user(self, user_id: int, data: dict) -> None:
        await self._send(self.users.get(user_id, set()), data)

    async def to_room(self, room_id: int, data: dict) -> None:
        await self._send(self.rooms.get(room_id, set()), data)

    def push_user(self, user_id: int, data: dict) -> None:
        """Gọi được từ luồng đồng bộ (route def thường hoặc bộ hẹn giờ)."""
        if not self.users.get(user_id):
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.to_user(user_id, data))
        except RuntimeError:
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.to_user(user_id, data), self.loop)

    def push_room(self, room_id: int, data: dict) -> None:
        if not self.rooms.get(room_id):
            return
        try:
            asyncio.get_running_loop().create_task(self.to_room(room_id, data))
        except RuntimeError:
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.to_room(room_id, data), self.loop)


hub = Hub()
