"""Điểm vào của ứng dụng: `uvicorn app.main:app --reload`."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .config import settings
from .db import Base, SessionLocal, engine
from .routers import admin, ai, auth, challenge, contests, documents, forum, leaderboard, payments, schedule, shop
from .seed import seed_challenges, seed_host, seed_plans
from .services import grading, judge, mailer, scheduler
from .services import ai as ai_service
from .services.realtime import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("codechalk")


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_plans(db)
        seed_host(db)
        ai_service.load_db_config(db)
        n = seed_challenges(db)
        if n:
            log.info("Đã nạp %d bài Challenge", n)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_production and settings.jwt_secret.startswith("doi-chuoi"):
        raise RuntimeError("Đặt JWT_SECRET ngẫu nhiên trong .env trước khi chạy production.")
    await asyncio.to_thread(init_db)
    hub.attach_loop()
    task = asyncio.create_task(scheduler.loop())
    grading.requeue_stale()
    yield
    task.cancel()


app = FastAPI(title="CodeChalk Platform API", version=__version__, lifespan=lifespan,
              description="Backend nền tảng học và thi lập trình CodeChalk.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=False)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = exc.errors()
    first = errs[0] if errs else {}
    msg = str(first.get("msg", "Dữ liệu không hợp lệ.")).replace("Value error, ", "")
    field = ".".join(str(x) for x in first.get("loc", [])[1:])
    return JSONResponse({"detail": msg, "field": field, "errors": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in errs[:10]]},
                        status_code=422)


for r in (auth.router, admin.router, payments.router, contests.router, contests.sub_router, leaderboard.router,
          schedule.router, documents.router, shop.router, forum.router, challenge.router, ai.router):
    app.include_router(r)


@app.get("/api/health", tags=["Hệ thống"])
def health():
    return {"ok": True, "version": __version__, "judge": judge.judge_info(), "ai": ai_service.enabled(), "email": mailer.enabled(),
            "payments": bool(settings.bank_account), "max_upload_mb": settings.max_upload_mb}


@app.get("/", include_in_schema=False)
def index():
    page = settings.web_dir / "index.html"
    if page.exists():
        return FileResponse(page, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"message": "CodeChalk API đang chạy. Đặt giao diện vào thư mục web/index.html hoặc mở /docs."})
