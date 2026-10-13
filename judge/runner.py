#!/usr/bin/env python3
"""Bộ chấm dùng chung: biên dịch rồi chạy code với từng test, so khớp output.

Chạy được theo hai cách:
  * import và gọi `judge_dir(path)` ngay trong server (JUDGE_MODE=local, chỉ dùng khi thử nghiệm);
  * bên trong container Docker cô lập: `python3 /judge/runner.py /box` (JUDGE_MODE=docker).

Thư mục làm việc chứa job.json:
  {"language": "cpp", "time_limit_ms": 2000, "memory_mb": 256, "tests": [{"input": "...", "expected": "..."}], "run_only": false}
và tệp mã nguồn (main.cpp / main.py / Main.java / main.js). Kết quả ghi vào result.json.
Chỉ dùng thư viện chuẩn của Python.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time

IS_WIN = os.name == "nt"
OUT_LIMIT = 1 << 20          # 1 MB output mỗi test
SRC_NAME = {"cpp": "main.cpp", "python": "main.py", "java": "Main.java", "javascript": "main.js"}


def _exe(name: str) -> str | None:
    return shutil.which(name)


def _python_cmd() -> list[str]:
    return [sys.executable or _exe("python3") or "python3", "-X", "utf8", "-B"]


def compile_cmd(lang: str, wd: str) -> list[str] | None:
    if lang == "cpp":
        gxx = _exe("g++") or _exe("clang++")
        if not gxx:
            raise FileNotFoundError("Máy chấm chưa cài g++. Cài MinGW-w64/MSYS2 (Windows) hoặc dùng JUDGE_MODE=docker.")
        out = os.path.join(wd, "main.exe" if IS_WIN else "main")
        return [gxx, "-std=gnu++17", "-O2", "-pipe", "-o", out, os.path.join(wd, "main.cpp")]
    if lang == "java":
        javac = _exe("javac")
        if not javac:
            raise FileNotFoundError("Máy chấm chưa cài JDK (javac).")
        return [javac, "-encoding", "UTF-8", "-d", wd, os.path.join(wd, "Main.java")]
    if lang == "python":
        return _python_cmd() + ["-m", "py_compile", os.path.join(wd, "main.py")]
    return None


def run_cmd(lang: str, wd: str) -> list[str]:
    if lang == "cpp":
        return [os.path.join(wd, "main.exe" if IS_WIN else "main")]
    if lang == "python":
        return _python_cmd() + [os.path.join(wd, "main.py")]
    if lang == "java":
        return [_exe("java") or "java", "-Xss64m", "-cp", wd, "Main"]
    if lang == "javascript":
        node = _exe("node")
        if not node:
            raise FileNotFoundError("Máy chấm chưa cài Node.js.")
        return [node, os.path.join(wd, "main.js")]
    raise ValueError("Ngôn ngữ không hỗ trợ: " + lang)


def _limits(mem_mb: int, cpu_s: int):
    if IS_WIN:
        return None

    def apply():  # chạy trong tiến trình con trước khi exec
        import resource
        os.setsid()
        if mem_mb:
            b = mem_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (b, b))
            except (ValueError, OSError):
                pass
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 << 20, 16 << 20))
        try:
            resource.setrlimit(resource.RLIMIT_STACK, (256 << 20, 256 << 20))
        except (ValueError, OSError):
            pass
    return apply


def _kill(p: subprocess.Popen) -> None:
    try:
        if IS_WIN:
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            p.kill()
        except OSError:
            pass


# Chỉ chuyển những biến môi trường cần để chạy trình biên dịch. Không bao giờ để code của thí sinh
# đọc được JWT_SECRET, AI_API_KEY, mật khẩu SMTP hay DATABASE_URL của máy chủ.
_KEEP_ENV = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
             "JAVA_HOME", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")


def _clean_env() -> dict:
    env = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", OPENBLAS_NUM_THREADS="1",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", HOME=os.environ.get("TMPDIR", "/tmp")
               if not IS_WIN else os.environ.get("TEMP", ""))
    return env


def execute(cmd: list[str], stdin: str, time_limit_ms: int, mem_mb: int, cwd: str) -> dict:
    """Chạy một lần. Trả về {stdout, stderr, code, signal, ms, tle}."""
    wall = time_limit_ms / 1000 * 2 + 0.5            # giới hạn thời gian thực (rộng hơn giới hạn CPU)
    cpu = max(1, int(time_limit_ms / 1000 + 1))
    env = _clean_env()
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                         preexec_fn=_limits(mem_mb, cpu),
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0)
    tle = False
    try:
        out, err = p.communicate(stdin.encode("utf-8"), timeout=wall)
    except subprocess.TimeoutExpired:
        tle = True
        _kill(p)
        out, err = p.communicate()
    ms = int((time.perf_counter() - t0) * 1000)
    code = p.returncode
    sig = -code if (code is not None and code < 0) else 0
    if sig in (getattr(signal, "SIGXCPU", 24), getattr(signal, "SIGKILL", 9)) and ms >= time_limit_ms * 0.9:
        tle = True
    if ms > time_limit_ms:
        tle = True
    return {"stdout": out[:OUT_LIMIT].decode("utf-8", "replace"), "stderr": err[:20000].decode("utf-8", "replace"),
            "code": code, "signal": sig, "ms": ms, "tle": tle, "ole": len(out) > OUT_LIMIT}


def _num(tok: str):
    try:
        return float(tok)
    except ValueError:
        return None


def same_output(actual: str, expected: str, eps: float = 1e-5) -> bool:
    """So khớp theo từng token, bỏ qua khác biệt khoảng trắng.
    Token số thực trong đáp án (có dấu chấm hoặc mũ e) được chấp nhận sai lệch tương đối/tuyệt đối eps,
    nên in 3.1416 hay 3.141593 cho đáp án 3.14159265 đều cần đủ độ chính xác theo đề (đề ghi rõ số chữ số)."""
    a, e = actual.split(), expected.split()
    if a == e:
        return True
    if len(a) != len(e):
        return False
    for x, y in zip(a, e):
        if x == y:
            continue
        if not any(ch in y for ch in ".eE") or y.lower() in ("inf", "nan"):
            return False
        fx, fy = _num(x), _num(y)
        if fx is None or fy is None:
            return False
        if abs(fx - fy) > max(eps, eps * abs(fy)):
            return False
    return True


SIG_NAME = {11: "Segmentation fault (truy cập bộ nhớ sai hoặc đệ quy quá sâu)", 8: "Floating point exception (chia số nguyên cho 0)",
            6: "Aborted (abort/assert hoặc ngoại lệ không được bắt)", 9: "Bị dừng (vượt giới hạn tài nguyên)", 24: "Vượt giới hạn CPU"}


def judge_dir(wd: str) -> dict:
    job = json.load(open(os.path.join(wd, "job.json"), encoding="utf-8"))
    lang, tl, mem = job["language"], int(job.get("time_limit_ms", 2000)), int(job.get("memory_mb", 256))
    res: dict = {"verdict": "", "compile": "", "tests": [], "passed": 0, "total": len(job.get("tests", [])), "max_ms": 0}
    try:
        cc = compile_cmd(lang, wd)
        if cc:
            c = execute(cc, "", 30000, 0 if lang == "java" else 2048, wd)
            if c["code"] != 0 or c["tle"]:
                msg = (c["stderr"] or c["stdout"] or "Biên dịch quá lâu.").replace(wd + os.sep, "").replace(wd + "/", "")
                res.update(verdict="CE", compile=msg[:6000])
                return res
            res["compile"] = c["stderr"].replace(wd + os.sep, "").replace(wd + "/", "")[:3000]   # cảnh báo
        cmd = run_cmd(lang, wd)
    except FileNotFoundError as e:
        res.update(verdict="SE", compile=str(e))
        return res
    for i, t in enumerate(job.get("tests", [])):
        lim = 0 if lang in ("java", "javascript") else (max(mem, 1024) if lang == "python" else mem)
        r = execute(cmd, t.get("input", ""), tl, lim, wd)
        item = {"i": i, "ms": min(r["ms"], tl * 2), "stdout": r["stdout"][:4000] if job.get("run_only") or t.get("show") else "",
                "stderr": r["stderr"][-4000:]}
        if r["tle"]:
            item["v"] = "TLE"
        elif r["ole"]:
            item["v"] = "OLE"
        elif r["code"] != 0:
            item["v"] = "RE"
            item["exit"] = r["code"]
            if r["signal"]:
                item["why"] = SIG_NAME.get(r["signal"], "Tín hiệu %d" % r["signal"])
            if "MemoryError" in r["stderr"] or "bad_alloc" in r["stderr"]:
                item["v"] = "MLE"
                item["why"] = "Vượt giới hạn bộ nhớ %d MB" % mem
        elif job.get("run_only"):
            item["v"] = "OK"
        else:
            item["v"] = "AC" if same_output(r["stdout"], t.get("expected", "")) else "WA"
        res["tests"].append(item)
        res["max_ms"] = max(res["max_ms"], item["ms"])
        if item["v"] in ("AC", "OK"):
            res["passed"] += 1
    bad = next((x["v"] for x in res["tests"] if x["v"] not in ("AC", "OK")), None)
    res["verdict"] = "OK" if job.get("run_only") and not bad else (bad or "AC")
    return res


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "/box"
    out = judge_dir(d)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
