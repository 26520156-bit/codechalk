"""Chấm code: cục bộ (thử nghiệm), Docker cô lập (khuyên dùng) hoặc Judge0."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ROOT, settings
from .http import post_json

sys.path.insert(0, str(ROOT / "judge"))
import runner  # noqa: E402  (judge/runner.py)

log = logging.getLogger("codechalk.judge")
_sem: asyncio.Semaphore | None = None

JUDGE0_LANG = {"cpp": 54, "python": 71, "java": 62, "javascript": 63}   # Judge0 CE: GCC 9.2, Python 3.8, OpenJDK 13, Node 12


@dataclass
class JudgeResult:
    verdict: str                     # AC WA TLE RE MLE OLE CE SE OK
    passed: int = 0
    total: int = 0
    max_ms: int = 0
    compile: str = ""
    tests: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "passed": self.passed, "total": self.total, "max_ms": self.max_ms,
                "compile": self.compile, "tests": self.tests}


def _sema() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(max(1, settings.judge_max_parallel))
    return _sem


def _prepare(lang: str, code: str, tests: list[dict], tl: int, mem: int, run_only: bool) -> str:
    base = settings.judge_work_dir or None
    if base:
        os.makedirs(base, exist_ok=True)
    wd = tempfile.mkdtemp(prefix="cc_judge_", dir=base)
    Path(wd, runner.SRC_NAME[lang]).write_text(code, encoding="utf-8")
    Path(wd, "job.json").write_text(json.dumps({"language": lang, "time_limit_ms": tl, "memory_mb": mem, "tests": tests,
                                                "run_only": run_only}, ensure_ascii=False), encoding="utf-8")
    return wd


def _local(wd: str) -> dict:
    return runner.judge_dir(wd)


def _box_mount(wd: str) -> list[str]:
    """Gắn thư mục bài nộp vào /box của container chấm.
    Máy chủ chạy thẳng trên máy: gắn đường dẫn thật. Máy chủ chạy trong Docker (docker compose):
    gắn đúng thư mục con của volume dùng chung, để code thí sinh không thấy bài của người khác."""
    if settings.judge_docker_volume:
        return ["--mount", f"type=volume,source={settings.judge_docker_volume},target=/box,volume-subpath={os.path.basename(wd)}"]
    return ["-v", f"{wd}:/box"]


def _docker(wd: str, tl: int, n: int, mem: int) -> dict:
    budget = 60 + n * (tl / 1000 * 2 + 1)
    os.chmod(wd, 0o777)                                   # container chạy bằng user không đặc quyền
    cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", f"{max(mem, 128) + 256}m",
           "--pids-limit", "128", "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
           "--user", "65534:65534", "--read-only", "--tmpfs", "/tmp:rw,exec,size=64m",
           *_box_mount(wd), "-w", "/box", settings.judge_docker_image, "python3", "/judge/runner.py", "/box"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=budget)
    except FileNotFoundError:
        return {"verdict": "SE", "compile": "Không tìm thấy lệnh docker. Cài Docker Desktop hoặc đặt JUDGE_MODE=local.", "tests": []}
    except subprocess.TimeoutExpired:
        return {"verdict": "TLE", "compile": "", "tests": []}
    rp = Path(wd, "result.json")
    if not rp.exists():
        return {"verdict": "SE", "compile": ("Container chấm bài lỗi: " + (p.stderr or p.stdout))[:2000], "tests": []}
    return json.loads(rp.read_text(encoding="utf-8"))


def _judge0(lang: str, code: str, tests: list[dict], tl: int, mem: int, run_only: bool) -> dict:
    headers = {"X-Auth-Token": settings.judge0_token} if settings.judge0_token else {}
    b64 = lambda s: base64.b64encode((s or "").encode()).decode()  # noqa: E731
    out = {"verdict": "", "compile": "", "tests": [], "passed": 0, "total": len(tests), "max_ms": 0}
    url = settings.judge0_url.rstrip("/") + "/submissions?base64_encoded=true&wait=true"
    for i, t in enumerate(tests):
        body = {"source_code": b64(code), "language_id": JUDGE0_LANG[lang], "stdin": b64(t.get("input", "")),
                "cpu_time_limit": tl / 1000, "memory_limit": mem * 1024}
        if not run_only:
            body["expected_output"] = b64(t.get("expected", ""))
        r = post_json(url, body, headers, timeout=60)
        sid = (r.get("status") or {}).get("id", 13)
        dec = lambda k: base64.b64decode(r.get(k) or b"").decode("utf-8", "replace")  # noqa: E731
        if sid == 6:
            out.update(verdict="CE", compile=dec("compile_output")[:6000])
            return out
        v = {3: "OK" if run_only else "AC", 4: "WA", 5: "TLE"}.get(sid, "RE" if 7 <= sid <= 12 else "SE")
        if v == "WA" and runner.same_output(dec("stdout"), t.get("expected", "")):
            v = "AC"
        ms = int(float(r.get("time") or 0) * 1000)
        out["tests"].append({"i": i, "v": v, "ms": ms, "stdout": dec("stdout")[:4000] if run_only else "", "stderr": dec("stderr")[-4000:]})
        out["max_ms"] = max(out["max_ms"], ms)
        out["passed"] += v in ("AC", "OK")
    bad = next((x["v"] for x in out["tests"] if x["v"] not in ("AC", "OK")), None)
    out["verdict"] = bad or ("OK" if run_only else "AC")
    return out


def _sync_judge(lang: str, code: str, tests: list[dict], tl: int, mem: int, run_only: bool) -> JudgeResult:
    if lang not in runner.SRC_NAME:
        return JudgeResult("SE", compile="Ngôn ngữ không hỗ trợ.")
    if settings.judge_mode == "judge0":
        raw = _judge0(lang, code, tests, tl, mem, run_only)
    else:
        wd = _prepare(lang, code, tests, tl, mem, run_only)
        try:
            raw = _docker(wd, tl, len(tests), mem) if settings.judge_mode == "docker" else _local(wd)
        finally:
            shutil.rmtree(wd, ignore_errors=True)
    tests_out = raw.get("tests", [])
    return JudgeResult(verdict=raw.get("verdict", "SE"), passed=sum(1 for t in tests_out if t.get("v") in ("AC", "OK")),
                       total=len(tests), max_ms=max([t.get("ms", 0) for t in tests_out] or [0]),
                       compile=raw.get("compile", ""), tests=tests_out)


async def judge(lang: str, code: str, tests: list[dict], time_limit_ms: int = 2000, memory_mb: int = 256,
                run_only: bool = False) -> JudgeResult:
    """tests: [{"input": str, "expected": str}]. Chạy trong luồng riêng để không chặn server."""
    async with _sema():
        try:
            return await asyncio.to_thread(_sync_judge, lang, code, tests, time_limit_ms, memory_mb, run_only)
        except Exception as e:  # lỗi hạ tầng, không phải lỗi code của thí sinh
            log.exception("judge failed")
            return JudgeResult("SE", compile=f"Lỗi máy chấm: {e}")


def available_languages() -> dict[str, bool]:
    if settings.judge_mode != "local":
        return {k: True for k in runner.SRC_NAME}
    return {"cpp": bool(shutil.which("g++") or shutil.which("clang++")), "python": True,
            "java": bool(shutil.which("javac")), "javascript": bool(shutil.which("node"))}


def judge_info() -> dict:
    return {"mode": settings.judge_mode, "languages": available_languages(), "python": sys.version.split()[0],
            "platform": os.name}
