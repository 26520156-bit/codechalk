"""Kiểm thử luồng chính của nền tảng (chạy: pytest -q)."""
import io
import time
from datetime import datetime, timedelta, timezone

import pytest

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
CPP_SUM = '#include <bits/stdc++.h>\nusing namespace std;\nint main(){long long a,b;cin>>a>>b;cout<<a+b<<"\\n";}'
CPP_WRONG = '#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a-b;}'
PY_SUM = 'a, b = map(int, input().split())\nprint(a + b)'


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def register(c, email, phone="0901234567", name="", password="matkhau123"):
    r = c.post("/api/auth/register", json={"email": email, "password": password, "phone": phone, "full_name": name})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def login(c, email, password):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def wait_sub(c, tok, sid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = c.get(f"/api/submissions/{sid}", headers=H(tok)).json()
        if s["status"] in ("DONE", "ERROR"):
            return s
        time.sleep(0.3)
    raise AssertionError("chấm quá lâu")


@pytest.fixture(scope="module")
def users(client):
    c = client
    st = register(c, "an@uit.vn", "0911111111", "Lê An")
    st2 = register(c, "binh@uit.vn", "0922222222", "Trần Bình")
    st3 = register(c, "chi@uit.vn", "0933333333", "Phạm Chi")
    host = login(c, "host@test.vn", "host-pass-123")
    teacher = register(c, "gv@uit.vn", "0944444444", "Cô Hà")
    me = c.get("/api/auth/me", headers=H(teacher)).json()
    r = c.patch(f"/api/admin/users/{me['id']}", json={"role": "TEACHER"}, headers=H(host))
    assert r.status_code == 200 and r.json()["role_label"] == "GIÁO VIÊN"
    return {"st": st, "st2": st2, "st3": st3, "host": host, "teacher": teacher}


def test_auth_rules(client, users):
    c = client
    assert c.post("/api/auth/register", json={"email": "an@uit.vn", "password": "matkhau123", "phone": "0911111111"}).status_code == 409
    r = c.post("/api/auth/register", json={"email": "x@y.vn", "password": "123", "phone": "0911111111"})
    assert r.status_code == 422 and "8 ký tự" in r.json()["detail"]
    r = c.post("/api/auth/register", json={"email": "x@y.vn", "password": "matkhau123", "phone": "12345"})
    assert r.status_code == 422 and r.json()["field"] == "phone"
    assert c.post("/api/auth/login", json={"email": "an@uit.vn", "password": "sai-mat-khau"}).status_code == 401
    me = c.get("/api/auth/me", headers=H(users["st"])).json()
    assert me["role"] == "STUDENT" and me["role_label"] == "SINH VIÊN" and me["plans"] == ["TU_HOC"]
    assert c.get("/api/admin/users", headers=H(users["st"])).status_code == 403
    host_me = c.get("/api/auth/me", headers=H(users["host"])).json()
    assert host_me["role"] == "HOST" and host_me["phone"] == "0912345678"


def test_admin_users(client, users):
    c = client
    r = c.get("/api/admin/users?q=uit.vn", headers=H(users["host"])).json()
    assert r["total"] >= 4
    an = next(u for u in r["items"] if u["email"] == "an@uit.vn")
    r = c.patch(f"/api/admin/users/{an['id']}", json={"full_name": "Lê Văn An", "phone": "0988888888"}, headers=H(users["host"]))
    assert r.json()["full_name"] == "Lê Văn An" and r.json()["phone"] == "0988888888"
    host = c.get("/api/auth/me", headers=H(users["host"])).json()
    assert c.patch(f"/api/admin/users/{host['id']}", json={"role": "STUDENT"}, headers=H(users["host"])).status_code == 400
    assert c.get("/api/admin/stats", headers=H(users["host"])).json()["teachers"] == 1


def test_payment_flow(client, users):
    c = client
    plans = c.get("/api/plans").json()
    assert [p["id"] for p in plans] == ["TU_HOC", "ON_THI", "LOP_HOC"]
    me = c.get("/api/auth/me", headers=H(users["st"])).json()
    r = c.post("/api/payments/orders", json={"plan_id": "ON_THI"}, headers=H(users["st"]))
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["transfer_code"] == f"SUB_{me['id']}_ON_THI" and o["status"] == "PENDING"
    assert o["qr"]["payload"].startswith("000201010212") and "970415" in o["qr"]["payload"] and o["qr"]["image"].startswith("data:image/png")
    # đặt lại cùng gói khi đang chờ: trả về đơn cũ
    assert c.post("/api/payments/orders", json={"plan_id": "ON_THI"}, headers=H(users["st"])).json()["id"] == o["id"]
    assert c.post("/api/payments/orders", json={"plan_id": "TU_HOC"}, headers=H(users["st"])).status_code == 422
    pending = c.get("/api/admin/payments", headers=H(users["host"])).json()
    assert any(p["id"] == o["id"] for p in pending)
    r = c.post(f"/api/admin/payments/{o['id']}/approve", json={"note": "Đã nhận"}, headers=H(users["host"]))
    assert r.json()["status"] == "APPROVED"
    assert c.post(f"/api/admin/payments/{o['id']}/approve", json={}, headers=H(users["host"])).status_code == 400
    me = c.get("/api/auth/me", headers=H(users["st"])).json()
    assert "ON_THI" in me["plans"] and me["ai_quota"] == 300
    n = c.get("/api/notifications", headers=H(users["st"])).json()
    assert n["unread"] >= 1 and "Ôn thi" in n["items"][0]["title"]
    # HOST nhận thông báo có đơn mới
    hn = c.get("/api/notifications", headers=H(users["host"])).json()
    assert any("Đơn đăng ký gói mới" in x["title"] for x in hn["items"])


def make_contest(c, tok, kind, start_offset_min=-1, duration=60, mode="TESTS", tests=None):
    body = {"title": f"Phòng {kind} thử", "description": "Tính tổng hai số", "start_at": (NOW() + timedelta(minutes=start_offset_min)).isoformat(),
            "end_at": (NOW() + timedelta(minutes=start_offset_min + duration)).isoformat(), "duration_minutes": 30, "grading_mode": mode,
            "languages": ["cpp", "python"],
            "problems": [{"title": "Tổng hai số", "statement": "Cho a, b. In a + b.", "points": 100,
                          "tests": tests or [{"input": "1 2", "expected_output": "3", "is_sample": True},
                                             {"input": "1000000000 1000000000", "expected_output": "2000000000"},
                                             {"input": "-5 5", "expected_output": "0"}]}]}
    r = c.post(f"/api/contests?kind={kind}", json=body, headers=H(tok))
    assert r.status_code == 201, r.text
    return r.json()


def test_exam_flow(client, users):
    c = client
    assert c.post("/api/contests?kind=exam", json={"title": "x" * 5, "start_at": NOW().isoformat(), "end_at": (NOW() + timedelta(hours=1)).isoformat(),
                                                  "duration_minutes": 30}, headers=H(users["st"])).status_code == 403
    ex = make_contest(c, users["teacher"], "exam")
    assert ex["state"] == "ONGOING" and ex["is_owner"] and ex["problems"][0]["tests"]
    pid = ex["problems"][0]["id"]
    # chưa JOIN thì không nộp được, cũng chưa thấy đề
    assert c.get(f"/api/contests/{ex['id']}", headers=H(users["st"])).json()["problems"] == []
    assert c.post(f"/api/contests/{ex['id']}/problems/{pid}/submit", json={"language": "cpp", "code": CPP_SUM}, headers=H(users["st"])).status_code == 403
    for k in ("st", "st2", "st3"):
        j = c.post(f"/api/contests/{ex['id']}/join", headers=H(users[k])).json()
        assert j["me"] and j["problems"] and "tests" not in j["problems"][0]
    # chạy thử với test mẫu
    r = c.post(f"/api/contests/{ex['id']}/problems/{pid}/run", json={"language": "python", "code": PY_SUM, "input": ""}, headers=H(users["st"])).json()
    assert r["kind"] == "samples" and r["verdict"] == "AC" and r["tests"][0]["expected"] == "3"
    r = c.post(f"/api/contests/{ex['id']}/problems/{pid}/run", json={"language": "cpp", "code": CPP_SUM, "input": "40 2"}, headers=H(users["st"])).json()
    assert r["tests"][0]["stdout"].strip() == "42"
    s1 = c.post(f"/api/contests/{ex['id']}/problems/{pid}/submit", json={"language": "cpp", "code": CPP_SUM}, headers=H(users["st"])).json()
    s2 = c.post(f"/api/contests/{ex['id']}/problems/{pid}/submit", json={"language": "cpp", "code": CPP_WRONG}, headers=H(users["st2"])).json()
    s3 = c.post(f"/api/contests/{ex['id']}/problems/{pid}/submit", json={"language": "python", "code": "print(0)"}, headers=H(users["st3"])).json()
    r1, r2, r3 = wait_sub(c, users["st"], s1["id"]), wait_sub(c, users["st2"], s2["id"]), wait_sub(c, users["st3"], s3["id"])
    assert r1["verdict"] == "AC" and r1["score"] == 100
    assert r2["verdict"] in ("PART", "WA") and r2["passed"] == 0
    assert r3["verdict"] == "PART" and r3["passed"] == 1           # chỉ đúng test "-5 5" → 0
    # test ẩn không lộ input/expected
    assert all("input" not in t for t in r1["details"]["tests"])
    lb = c.get(f"/api/contests/{ex['id']}/leaderboard").json()
    assert [row["user"]["full_name"] for row in lb["rows"]][0] == "Lê Văn An"
    # giáo viên xem được mọi bài nộp
    assert len(c.get(f"/api/contests/{ex['id']}/submissions", headers=H(users["teacher"])).json()) == 3
    # kết thúc phòng → chốt BXH, cộng Bcoins Top 1 = 10
    from app.db import SessionLocal
    from app.models import Contest
    from app.services.contests import finalize_due
    with SessionLocal() as db:
        cc = db.get(Contest, ex["id"])
        cc.start_at, cc.end_at = NOW() - timedelta(hours=2), NOW() - timedelta(seconds=1)
        db.commit()
        assert finalize_due(db) >= 1
    lb = c.get(f"/api/contests/{ex['id']}/leaderboard").json()
    assert lb["state"] == "DONE" and lb["finalized"]
    assert [r["bcoins_awarded"] for r in lb["rows"]] == [10, 9, 0]   # người 0 điểm không nhận thưởng
    me = c.get("/api/auth/me", headers=H(users["st"])).json()
    assert me["bcoins"] == 10 and me["xp"] >= 20
    assert c.post(f"/api/contests/{ex['id']}/problems/{pid}/submit", json={"language": "cpp", "code": CPP_SUM}, headers=H(users["st"])).status_code == 400


def test_codewar_min_players_and_creator(client, users):
    c = client
    cw = make_contest(c, users["st2"], "codewar")
    pid = cw["problems"][0]["id"]
    for k in ("st2", "st3"):
        c.post(f"/api/contests/{cw['id']}/join", headers=H(users[k]))
        s = c.post(f"/api/contests/{cw['id']}/problems/{pid}/submit", json={"language": "python", "code": PY_SUM}, headers=H(users[k])).json()
        assert wait_sub(c, users[k], s["id"])["verdict"] == "AC"
    before = c.get("/api/auth/me", headers=H(users["st3"])).json()["bcoins"]
    from app.db import SessionLocal
    from app.models import Contest
    from app.services.contests import finalize
    with SessionLocal() as db:
        cc = db.get(Contest, cw["id"])
        cc.start_at, cc.end_at = NOW() - timedelta(hours=2), NOW() - timedelta(seconds=1)
        db.commit()
        finalize(db, cc)
    # chỉ 2 người có điểm (< 3): không trao Bcoins
    assert c.get("/api/auth/me", headers=H(users["st3"])).json()["bcoins"] == before
    assert c.get("/api/contests?kind=codewar").json()[0]["state"] in ("DONE", "ONGOING", "UPCOMING")


def test_cashout(client, users):
    c = client
    from app.db import SessionLocal
    from app.services import bcoins
    me = c.get("/api/auth/me", headers=H(users["st"])).json()
    with SessionLocal() as db:
        bcoins.change(db, me["id"], 290, "ADJUST", note="test")
        db.commit()
    assert c.get("/api/auth/me", headers=H(users["st"])).json()["bcoins"] == 300
    r = c.post("/api/shop/cashout", data={"bcoins": "150", "method": "BANK", "bank_account": "1", "bank_name": "A", "account_holder": "B"}, headers=H(users["st"]))
    assert r.status_code == 422
    r = c.post("/api/shop/cashout", data={"bcoins": "200", "method": "BANK", "bank_account": "0123456789", "bank_name": "Vietcombank",
                                          "account_holder": "LE VAN AN"}, headers=H(users["st"]))
    assert r.status_code == 201, r.text
    t1 = r.json()
    assert t1["amount_vnd"] == 20000 and t1["status"] == "PENDING"
    assert c.get("/api/auth/me", headers=H(users["st"])).json()["bcoins"] == 100
    r = c.post("/api/shop/cashout", data={"bcoins": "200", "method": "BANK", "bank_account": "0123", "bank_name": "V", "account_holder": "L"}, headers=H(users["st"]))
    assert r.status_code == 400 and "không đủ" in r.json()["detail"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = c.post("/api/shop/cashout", data={"bcoins": "100", "method": "QR"}, files={"qr_image": ("qr.png", png, "image/png")}, headers=H(users["st"]))
    assert r.status_code == 201 and r.json()["has_qr"]
    t2 = r.json()
    assert c.get(f"/api/shop/requests/{t2['id']}/qr", headers=H(users["host"])).status_code == 200
    adm = c.get("/api/admin/cashouts", headers=H(users["host"])).json()
    assert {t1["id"], t2["id"]} <= {x["id"] for x in adm}
    assert c.post(f"/api/admin/cashouts/{t1['id']}/complete", json={"note": "CK lúc 9h"}, headers=H(users["host"])).json()["status"] == "COMPLETED"
    assert c.post(f"/api/admin/cashouts/{t2['id']}/reject", json={"note": "QR mờ"}, headers=H(users["host"])).json()["status"] == "REJECTED"
    assert c.get("/api/auth/me", headers=H(users["st"])).json()["bcoins"] == 100      # được hoàn 100
    tx = c.get("/api/bcoins/me", headers=H(users["st"])).json()["transactions"]
    assert [t["reason"] for t in tx[:3]] == ["REFUND", "CASHOUT", "CASHOUT"]


def test_documents(client, users):
    c = client
    pdf = b"%PDF-1.4\n%test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    r = c.post("/api/documents", data={"title": "Giáo trình C++ chương 1", "description": "Biến, vòng lặp", "category": "Giáo trình"},
               files={"file": ("chuong1.pdf", pdf, "application/pdf")}, headers=H(users["st2"]))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ext"] == "pdf" and d["previewable"] and d["uploader"]["full_name"] == "Trần Bình"
    assert c.post("/api/documents", data={"title": "Virus"}, files={"file": ("a.exe", b"MZ", "application/x-msdownload")}, headers=H(users["st2"])).status_code == 400
    lst = c.get("/api/documents?q=giáo trình", headers=H(users["st"])).json()
    assert lst and lst[0]["id"] == d["id"] and not lst[0]["can_delete"]
    f = c.get(f"/api/documents/{d['id']}/file", headers=H(users["st"]))
    assert f.status_code == 200 and f.content == pdf and "attachment" in f.headers["content-disposition"]
    assert c.get(f"/api/documents/{d['id']}/file?inline=1&token={users['st']}").headers["content-type"].startswith("application/pdf")
    assert c.get("/api/documents", headers=H(users["st"])).json()[0]["downloads"] == 1
    assert c.delete(f"/api/documents/{d['id']}", headers=H(users["st"])).status_code == 403
    assert c.delete(f"/api/documents/{d['id']}", headers=H(users["st2"])).status_code == 200


def test_forum_realtime(client, users):
    c = client
    r = c.post("/api/rooms", data={"name": "Ôn thi cuối kỳ C++", "description": "Hỏi đáp", "kind": "ROOM"}, headers=H(users["st"]))
    assert r.status_code == 201
    room = r.json()
    assert room["joined"] and room["is_owner"]
    assert c.get(f"/api/rooms/{room['id']}/messages", headers=H(users["st2"])).status_code == 403
    c.post(f"/api/rooms/{room['id']}/join", headers=H(users["st2"]))
    with c.websocket_connect(f"/ws/rooms/{room['id']}?token={users['st2']}") as w2:
        assert w2.receive_json()["type"] == "presence"
        with c.websocket_connect(f"/ws/rooms/{room['id']}?token={users['st']}") as w1:
            assert w1.receive_json()["type"] == "presence"
            assert w2.receive_json()["type"] == "presence"
            w1.send_json({"type": "message", "content": "Chào cả nhà, ai giải bài 5 chưa?"})
            m = w2.receive_json()
            assert m["type"] == "message" and m["message"]["content"].startswith("Chào") and m["message"]["user"]["full_name"] == "Lê Văn An"
            r = c.post(f"/api/rooms/{room['id']}/messages", data={"content": "Ảnh đề nè"},
                       files={"file": ("de.png", b"\x89PNG\r\n\x1a\n" + b"1" * 32, "image/png")}, headers=H(users["st2"]))
            assert r.status_code == 201 and r.json()["attachment"]["is_image"]
            got = w1.receive_json()
            while got["type"] != "message" or not got["message"]["attachment"]:   # bỏ qua tin của chính mình
                got = w1.receive_json()
            assert got["message"]["attachment"]["name"] == "de.png"
            w1.send_json({"type": "read", "last_id": got["message"]["id"]})
            rd = w2.receive_json()
            while rd["type"] != "read":
                rd = w2.receive_json()
            assert rd["last_id"] == got["message"]["id"]
    msgs = c.get(f"/api/rooms/{room['id']}/messages", headers=H(users["st"])).json()
    assert len(msgs) == 2
    assert c.get(f"/api/messages/{msgs[1]['id']}/file?token={users['st']}").status_code == 200
    assert c.get(f"/api/messages/{msgs[1]['id']}/file?token={users['st3']}").status_code == 404   # không phải thành viên
    info = c.get(f"/api/rooms/{room['id']}", headers=H(users["st"])).json()
    assert info["members"] == 2 and len(info["member_list"]) == 2


def test_schedule_and_reminders(client, users):
    c = client
    start = NOW() + timedelta(minutes=3)
    r = c.post("/api/events", json={"title": "Luyện 5 bài mảng", "kind": "PRACTICE", "start_at": start.isoformat(), "remind_minutes": 10,
                                    "notify_email": True}, headers=H(users["st3"]))
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["next_remind_at"] is not None
    r = c.post("/api/events", json={"title": "Học Python mỗi tối", "start_at": (NOW() - timedelta(days=2)).isoformat(), "repeat": "DAILY",
                                    "remind_minutes": 0}, headers=H(users["st3"]))
    nxt = datetime.fromisoformat(r.json()["next_remind_at"])
    assert NOW() < nxt <= NOW() + timedelta(days=1)
    from app.services.scheduler import send_due_reminders
    assert send_due_reminders() >= 1
    n = c.get("/api/notifications?unread=true", headers=H(users["st3"])).json()
    assert any("Luyện 5 bài mảng" in x["title"] for x in n["items"])
    assert c.post("/api/notifications/read-all", headers=H(users["st3"])).status_code == 200
    assert c.get("/api/notifications?unread=true", headers=H(users["st3"])).json()["unread"] == 0
    assert c.put(f"/api/events/{ev['id']}", json={**{k: ev[k] for k in ("title", "kind", "start_at", "remind_minutes")}, "done": True},
                 headers=H(users["st3"])).json()["next_remind_at"] is None
    assert c.delete(f"/api/events/{ev['id']}", headers=H(users["st2"])).status_code == 404


def test_notify_websocket(client, users):
    c = client
    me = c.get("/api/auth/me", headers=H(users["st2"])).json()
    with c.websocket_connect(f"/ws/notify?token={users['st2']}") as w:
        c.post(f"/api/admin/users/{me['id']}/grant", json={"plan_id": "LOP_HOC", "days": 30}, headers=H(users["host"]))
        msg = w.receive_json()
        assert msg["type"] == "notification" and "Lớp học" in msg["item"]["title"]


def test_leaderboard(client, users):
    c = client
    r = c.get("/api/leaderboard?by=bcoins", headers=H(users["st"])).json()
    assert r["rows"][0]["bcoins"] >= r["rows"][-1]["bcoins"] and r["me"]["rank"] >= 1
    assert all(row["role"] != "HOST" for row in r["rows"])
    r = c.get("/api/leaderboard?by=xp").json()
    assert r["rows"][0]["xp"] >= 20


def test_challenge_and_ai(client, users, monkeypatch):
    c = client
    ch = c.get("/api/challenges/chapters", headers=H(users["st3"])).json()
    assert len(ch) == 13 and sum(x["count"] for x in ch) == 929
    assert [x["chapter"] for x in ch if not x["locked"]] == [1, 2, 3, 4, 5]
    assert c.get("/api/challenges/700").json()["locked"]
    assert c.post("/api/challenges/700/submit", json={"language": "cpp", "code": "int main(){}"}, headers=H(users["st3"])).status_code == 402
    p1 = c.get("/api/challenges/1", headers=H(users["st3"])).json()
    assert p1["has_tests"] and p1["samples"] and p1["next"] == 2
    r = c.post("/api/challenges/1/run", json={"language": "python", "code": "n=int(input())\nprint(n*(n+1)//2)", "input": ""}, headers=H(users["st3"])).json()
    assert r["verdict"] == "AC"
    s = c.post("/api/challenges/1/submit", json={"language": "cpp", "code": "#include <iostream>\nint main(){int n;std::cin>>n;std::cout<<n*(n+1)/2;}"},
               headers=H(users["st3"])).json()
    res = wait_sub(c, users["st3"], s["id"])
    assert res["verdict"] == "PART" and 0 < res["passed"] < res["total"]       # tràn int ở test lớn
    s = c.post("/api/challenges/1/submit", json={"language": "cpp", "code": "#include <iostream>\nint main(){long long n;std::cin>>n;std::cout<<n*(n+1)/2;}"},
               headers=H(users["st3"])).json()
    res = wait_sub(c, users["st3"], s["id"])
    assert res["verdict"] == "AC" and res["details"]["xp_gained"] == 10
    lst = c.get("/api/challenges?chapter=1", headers=H(users["st3"])).json()
    assert lst["total"] == 76 and lst["items"][0]["progress"]["solved"]
    # AI chưa cấu hình → báo rõ
    r = c.post("/api/ai/tutor", json={"mode": "HINT", "code": "int main(){}", "challenge_id": 1}, headers=H(users["st3"]))
    assert r.status_code == 503 and "AI chưa được bật" in r.json()["detail"]
    # Giả lập AI để kiểm tra luồng AI CHẤM của bài không có test
    from app.services import ai
    monkeypatch.setattr(ai, "complete", lambda *a, **k: _fake_ai())
    assert not c.get("/api/challenges/131").json()["has_tests"]
    s = c.post("/api/challenges/131/submit", json={"language": "cpp", "code": "void xuat(int a[], int n){ for(int i=0;i<n;i++) printf(\"%d \", a[i]); }"},
               headers=H(users["st3"])).json()
    res = wait_sub(c, users["st3"], s["id"])
    assert res["verdict"] == "AI" and res["score"] == 92.0 and res["details"]["xp_gained"] == 20


def test_challenge_ai_coach(client, users, monkeypatch):
    c = client
    from app.services import ai
    host, st, st3 = users["host"], users["st2"], users["st3"]
    # HOST bật AI ngay trên giao diện (không cần sửa .env)
    assert c.get("/api/admin/ai", headers=H(st)).status_code == 403
    a = c.get("/api/admin/ai", headers=H(host)).json()
    assert not a["enabled"] and len(a["providers"]) == 4
    assert c.put("/api/admin/ai", json={"provider": "gemini"}, headers=H(host)).status_code == 400
    a = c.put("/api/admin/ai", json={"provider": "gemini", "api_key": "AIza-test-key-123456", "model": ""}, headers=H(host)).json()
    assert a["enabled"] and a["key_hint"] == "…3456" and a["effective_model"] == "gemini-3.5-flash-lite" and "api_key" not in a
    assert c.get("/api/health").json()["ai"]
    a = c.put("/api/admin/ai", json={"provider": "gemini", "model": "gemini-3.8-flash"}, headers=H(host)).json()
    assert a["key_set"] and a["effective_model"] == "gemini-3.8-flash"          # bỏ trống khoá = giữ khoá cũ

    calls = []
    wrong = "```python\nn = int(input())\nprint(n * (n + 1) * (2 * n + 1) // 7)\n```"
    right = "```python\nn = int(input())\nprint(n * (n + 1) * (2 * n + 1) // 6)\n```"

    async def fake(system, prompt, want_json=False, max_tokens=2048, c=None):
        calls.append(prompt)
        if "NHIỆM VỤ: VIẾT CODE ĐÁP ÁN" in prompt:
            body = right if "KẾT QUẢ CHẠY THẬT" in prompt else wrong
            return f"## Ý tưởng\nDùng công thức n(n+1)(2n+1)/6.\n## Độ phức tạp\nO(1)\n## Code\n{body}\n## Giải thích từng bước\n- In kết quả."
        if "NHIỆM VỤ: SỬA LỖI GIÚP" in prompt:
            return ("## Lỗi tìm thấy\n- **Dòng 2**: `int` bị tràn số khi n lớn.\n## Code đã sửa\n```cpp\n#include <iostream>\n"
                    "int main(){long long n;std::cin>>n;std::cout<<n*(n+1)*(2*n+1)/6;}\n```\n## Ghi chú\nDùng long long.")
        return "## Gợi ý\nNghĩ về công thức tổng bình phương."
    monkeypatch.setattr(ai, "complete", fake)

    r = c.post("/api/challenges/2/ai", json={"mode": "SUGGEST", "language": "python", "code": ""}, headers=H(st)).json()
    assert r["text"].startswith("## Gợi ý") and r["help"] is None and r["xp_rule"] == "Giữ nguyên XP"
    assert c.post("/api/challenges/2/ai", json={"mode": "FIX", "language": "cpp", "code": ""}, headers=H(st)).status_code == 400
    assert c.post("/api/challenges/700/ai", json={"mode": "HINT"}, headers=H(st3)).status_code == 402    # chương bị khoá

    # Sửa lỗi giúp: code AI sửa được chạy thật trên bộ test; giải bằng nó chỉ còn 50% XP
    bad = "#include <iostream>\nint main(){int n;std::cin>>n;std::cout<<n*(n+1)*(2*n+1)/6;}"
    r = c.post("/api/challenges/2/ai", json={"mode": "FIX", "language": "cpp", "code": bad, "verdict": "PART"}, headers=H(st)).json()
    assert "long long" in r["code"] and r["verify"]["ok"] and r["verify"]["passed"] == r["verify"]["total"] == 7
    assert r["help"] == "FIX" and "## Lỗi tìm thấy" in r["text"] and "```" not in r["text"]
    s = c.post("/api/challenges/2/submit", json={"language": "cpp", "code": r["code"]}, headers=H(st)).json()
    res = wait_sub(c, st, s["id"])
    assert res["verdict"] == "AC" and res["details"]["xp_gained"] == 5 and "5/10" in res["details"]["xp_note"]

    # Đáp án: bản đầu sai → máy chấm phát hiện → AI sửa lại một lần → đúng hết và được lưu dùng chung
    n0 = len(calls)
    r = c.post("/api/challenges/2/ai", json={"mode": "SOLUTION", "language": "python"}, headers=H(st)).json()
    assert r["attempts"] == 2 and r["verify"]["ok"] and "// 6" in r["code"] and not r["cached"] and len(calls) == n0 + 2
    assert r["help"] == "FIX"                       # đã giải xong trước đó nên không đổi mức trợ giúp
    used0 = c.get("/api/ai/status", headers=H(st3)).json()["used_today"]
    r = c.post("/api/challenges/2/ai", json={"mode": "SOLUTION", "language": "python"}, headers=H(st3)).json()
    assert r["cached"] and r["help"] == "SOLUTION" and len(calls) == n0 + 2
    assert c.get("/api/ai/status", headers=H(st3)).json()["used_today"] == used0       # đáp án đã lưu không tốn lượt AI
    assert c.get("/api/challenges/2", headers=H(st3)).json()["help"] == "SOLUTION"
    s = c.post("/api/challenges/2/submit", json={"language": "python", "code": r["code"]}, headers=H(st3)).json()
    res = wait_sub(c, st3, s["id"])
    assert res["verdict"] == "AC" and res["details"]["xp_gained"] == 0 and "không cộng XP" in res["details"]["xp_note"]

    assert not c.put("/api/admin/ai", json={"provider": "none"}, headers=H(host)).json()["enabled"]


async def _fake_ai():
    return '{"correctness": 100, "efficiency": 80, "clean_code": 80, "complexity": "O(sqrt n)", "summary": "Đúng.", "issues": [], "suggestions": []}'


def test_health(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["payments"] and h["judge"]["languages"]["cpp"]
