"""HTTP JSON tối giản bằng thư viện chuẩn (dùng cho AI và Judge0)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def post_json(url: str, body: dict, headers: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json", **(headers or {})})
    return _send(req, timeout)


def get_json(url: str, headers: dict | None = None, timeout: float = 30) -> dict:
    return _send(urllib.request.Request(url, method="GET", headers=headers or {}), timeout)


def _send(req: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(raw)
            msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or j.get("message") or raw
        except ValueError:
            msg = raw
        raise HttpError(e.code, str(msg)[:500]) from None
    except urllib.error.URLError as e:
        raise HttpError(0, f"Không kết nối được: {e.reason}") from None
    except TimeoutError:
        raise HttpError(0, "Hết thời gian chờ phản hồi") from None
