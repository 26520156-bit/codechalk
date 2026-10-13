"""Gọi mô hình AI (Gemini / Claude / OpenAI) cho AI CHẤM và Trợ lý lập trình."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from ..config import ROOT, settings
from .http import HttpError, get_json, post_json

log = logging.getLogger("codechalk.ai")

LANG_NAME = {"cpp": "C++17", "python": "Python 3", "java": "Java", "javascript": "JavaScript (Node.js)"}

# Nhà cung cấp AI. key=False: không cần khoá (Ollama chạy ngay trên máy).
PROVIDERS = {
    "gemini": {"name": "Google Gemini", "model": "gemini-3.5-flash-lite", "key": True,
               "key_url": "https://aistudio.google.com/apikey", "key_hint": "AIza…"},
    "anthropic": {"name": "Claude (Anthropic)", "model": "claude-sonnet-5-5", "key": True,
                  "key_url": "https://platform.claude.com/settings/keys", "key_hint": "sk-ant-…"},
    "openai": {"name": "OpenAI hoặc dịch vụ tương thích OpenAI", "model": "gpt-5.4-mini", "key": True,
               "key_url": "https://platform.openai.com/api-keys", "key_hint": "sk-…"},
    "ollama": {"name": "Ollama (chạy trên máy, không cần khoá)", "model": "", "key": False,
               "key_url": "https://ollama.com/download", "key_hint": "", "base": "http://localhost:11434/v1"},
}
DEFAULT_MODEL = {k: v["model"] for k, v in PROVIDERS.items()}

# Cấu hình HOST lưu trong CSDL (Quản trị → AI), ưu tiên hơn .env. Nạp khi khởi động.
_db_cfg: dict[str, str] = {}
CFG_KEYS = ("ai.provider", "ai.api_key", "ai.model", "ai.base_url")


class AIUnavailable(Exception):
    pass


def load_db_config(db) -> None:
    from ..models import AppSetting
    _db_cfg.clear()
    for row in db.query(AppSetting).filter(AppSetting.key.in_(CFG_KEYS)).all():
        _db_cfg[row.key] = row.value or ""


def save_db_config(db, values: dict[str, str]) -> None:
    from ..models import AppSetting
    for k, v in values.items():
        row = db.get(AppSetting, k)
        if row is None:
            db.add(AppSetting(key=k, value=v))
        else:
            row.value = v
    db.commit()
    load_db_config(db)


def cfg() -> dict:
    """Cấu hình AI đang dùng: lấy từ Quản trị → AI nếu HOST đã lưu, nếu không thì từ .env."""
    if _db_cfg.get("ai.provider"):
        p = _db_cfg.get("ai.provider", "")
        return {"provider": p, "key": _db_cfg.get("ai.api_key", ""), "model": _db_cfg.get("ai.model", ""),
                "base": _db_cfg.get("ai.base_url", ""), "source": "admin"}
    return {"provider": settings.ai_provider, "key": settings.ai_api_key, "model": settings.ai_model,
            "base": settings.ai_base_url, "source": "env"}


def _usable(c: dict) -> bool:
    meta = PROVIDERS.get(c["provider"])
    return bool(meta) and (bool(c["key"]) or not meta["key"]) and bool(c["model"] or meta["model"])


def enabled() -> bool:
    return _usable(cfg())


def model_name() -> str:
    c = cfg()
    return c["model"] or DEFAULT_MODEL.get(c["provider"], "")


def _base(c: dict) -> str:
    if c["provider"] == "ollama":
        return (c["base"] or PROVIDERS["ollama"]["base"]).rstrip("/")
    return (c["base"] or "https://api.openai.com/v1").rstrip("/")


def _complete_sync(system: str, user: str, want_json: bool, max_tokens: int, c: dict | None = None) -> str:
    c = c or cfg()
    if not PROVIDERS.get(c["provider"]) or (PROVIDERS[c["provider"]]["key"] and not c["key"]):
        raise AIUnavailable(NOT_CONFIGURED)
    p, key = c["provider"], c["key"]
    model = c["model"] or DEFAULT_MODEL.get(p, "")
    if not model:
        raise AIUnavailable("Chưa chọn model AI. HOST vào Quản trị → AI để chọn model.")
    if p == "gemini":
        # Gemini 3 có bước "suy nghĩ" tính vào maxOutputTokens: chừa thêm để không bị cắt câu trả lời.
        body = {"contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens + 4096}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if want_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        j = post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", body, timeout=120)
        cand = (j.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(x.get("text", "") for x in parts if not x.get("thought"))
        if not text and cand.get("finishReason") in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise AIUnavailable("Gemini từ chối trả lời câu này (bộ lọc an toàn). Hãy hỏi lại theo cách khác.")
        return text
    if p == "anthropic":
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": user}]}
        if system:
            body["system"] = system
        j = post_json("https://api.anthropic.com/v1/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=120)
        return "".join(x.get("text", "") for x in j.get("content", []) if x.get("type") == "text")
    base = _base(c)
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    body = {"model": model, "messages": msgs}
    # API chính thức của OpenAI dùng max_completion_tokens; Ollama và dịch vụ tương thích dùng max_tokens.
    body["max_completion_tokens" if "api.openai.com" in base else "max_tokens"] = max_tokens + (4096 if "api.openai.com" in base else 0)
    if want_json:
        body["response_format"] = {"type": "json_object"}
    headers = {"authorization": "Bearer " + key} if key else {}
    j = post_json(base + "/chat/completions", body, headers, timeout=180 if p == "ollama" else 120)
    return ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


NOT_CONFIGURED = ("AI chưa được bật trên máy chủ. HOST vào Quản trị → AI, chọn nhà cung cấp và dán khoá API "
                  "(Google Gemini có gói dùng miễn phí), hoặc chọn Ollama để chạy AI ngay trên máy.")


def explain_http_error(e: HttpError, model: str = "") -> str:
    m = (e.message or "").strip()
    low = m.lower()
    if e.status == 0:
        return f"Không kết nối được tới dịch vụ AI ({m}). Kiểm tra mạng, hoặc địa chỉ máy Ollama nếu dùng Ollama."
    if e.status in (401, 403) or "api key not valid" in low or "invalid x-api-key" in low or "incorrect api key" in low:
        return "Khoá API không hợp lệ hoặc không có quyền dùng model này. HOST kiểm tra lại khoá trong Quản trị → AI."
    if e.status == 404 or "not found" in low:
        return f"Không tìm thấy model “{model}”. HOST vào Quản trị → AI, bấm “Tải danh sách model” để chọn đúng tên."
    if e.status == 429 or "quota" in low or "rate limit" in low:
        return "Dịch vụ AI báo hết hạn mức (gọi quá nhanh hoặc hết lượt miễn phí). Thử lại sau ít phút."
    if e.status >= 500:
        return "Dịch vụ AI đang quá tải hoặc gặp lỗi. Thử lại sau ít phút."
    return f"AI trả lỗi ({e.status}): {m[:300]}"


async def complete(system: str, user: str, want_json: bool = False, max_tokens: int = 2048, c: dict | None = None) -> str:
    try:
        text = await asyncio.to_thread(_complete_sync, system, user, want_json, max_tokens, c)
    except HttpError as e:
        raise AIUnavailable(explain_http_error(e, (c or cfg()).get("model") or model_name())) from None
    if not (text or "").strip():
        raise AIUnavailable("AI không trả lời (câu trả lời rỗng). Thử lại, hoặc đổi sang model khác trong Quản trị → AI.")
    return text


def list_models(provider: str, key: str, base: str = "") -> list[str]:
    """Danh sách model thật của nhà cung cấp, để HOST chọn đúng tên."""
    try:
        if provider == "gemini":
            j = get_json(f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}")
            out = [m["name"].split("/", 1)[-1] for m in j.get("models", [])
                   if "generateContent" in (m.get("supportedGenerationMethods") or [])]
            return sorted(out, key=lambda x: (("embedding" in x) or ("tts" in x) or ("image" in x), x))
        if provider == "anthropic":
            j = get_json("https://api.anthropic.com/v1/models?limit=100", {"x-api-key": key, "anthropic-version": "2023-06-01"})
            return [m["id"] for m in j.get("data", [])]
        c = {"provider": provider, "key": key, "base": base, "model": ""}
        headers = {"authorization": "Bearer " + key} if key else {}
        j = get_json(_base(c) + "/models", headers)
        return sorted(m["id"] for m in j.get("data", []))
    except HttpError as e:
        raise AIUnavailable(explain_http_error(e)) from None


def parse_json(text: str) -> dict:
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except ValueError:
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            return json.loads(s[a:b + 1])
        raise


# ---------- AI CHẤM ----------
GRADER_SYSTEM = """Bạn là giám khảo chấm bài lập trình cho sinh viên năm nhất. Trả lời bằng tiếng Việt, chỉ xuất JSON đúng lược đồ.
Nguyên tắc:
- Đọc kỹ đề và code. Chỉ kết luận điều chắc chắn suy ra được từ code; không bịa kết quả chạy.
- Nếu có "kết quả chạy thử trên test mẫu" thì đó là sự thật đã đo, phải dùng làm căn cứ chính cho điểm đúng đắn.
- Chấm 3 tiêu chí, mỗi tiêu chí 0..100: correctness (đúng đắn với mọi input hợp lệ trong ràng buộc, kể cả biên),
  efficiency (độ phức tạp so với ràng buộc), clean_code (đặt tên, cấu trúc, không lặp, dễ đọc).
- Code không biên dịch được / sai cú pháp: correctness = 0.
- Nhận xét ngắn gọn, chỉ rõ số dòng khi nói về lỗi. Không viết lại toàn bộ lời giải.
Lược đồ: {"correctness": int, "efficiency": int, "clean_code": int, "complexity": "O(...)", "summary": "1-2 câu",
"issues": [{"line": int|null, "severity": "loi|canh_bao|goi_y", "message": "..."}], "suggestions": ["..."]}"""


async def grade(statement: str, language: str, code: str, sample_report: str = "") -> dict:
    numbered = "\n".join(f"{i + 1:>3}| {l}" for i, l in enumerate(code.splitlines()))
    user = f"ĐỀ BÀI:\n{statement}\n\nNGÔN NGỮ: {LANG_NAME.get(language, language)}\n\nCODE (có số dòng):\n{numbered}\n"
    if sample_report:
        user += f"\nKẾT QUẢ CHẠY THỬ TRÊN TEST MẪU (đo thật):\n{sample_report}\n"
    data = parse_json(await complete(GRADER_SYSTEM, user, want_json=True, max_tokens=1500))
    c = max(0, min(100, int(data.get("correctness", 0))))
    e = max(0, min(100, int(data.get("efficiency", 0))))
    q = max(0, min(100, int(data.get("clean_code", 0))))
    data["score"] = round(0.6 * c + 0.25 * e + 0.15 * q, 1) if c > 0 else 0.0
    data.update(correctness=c, efficiency=e, clean_code=q)
    return data


# ---------- Trợ lý lập trình ----------
def robot_prompt() -> str:
    p = ROOT / "app" / "prompts" / "robot_tro_giang.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


TUTOR_SYSTEM = """Bạn là Robot Trợ giảng của CodeChalk, hướng dẫn sinh viên năm nhất bằng tiếng Việt, xưng "mình", gọi "bạn".
Quy tắc:
- HINT: chỉ gợi ý hướng tư duy theo từng bậc (quan sát → ý tưởng → khung giải), KHÔNG đưa lời giải hoàn chỉnh.
- DEBUG: chỉ ra dòng gây lỗi (theo số dòng), giải thích nguyên nhân dễ hiểu, gợi ý cách sửa; trích thông báo lỗi nếu có.
- EXPLAIN: giải thích đoạn code hoặc khái niệm người học hỏi.
- Không bịa thông báo lỗi hay kết quả chạy. Không chắc thì nói rõ là giả thuyết và đề nghị cách kiểm chứng.
- Trả lời ngắn gọn bằng Markdown (đoạn văn ngắn, gạch đầu dòng, khối code nhỏ nếu cần)."""


async def tutor(mode: str, statement: str, language: str, code: str, question: str, verdict: str, error: str) -> str:
    numbered = "\n".join(f"{i + 1:>3}| {l}" for i, l in enumerate(code.splitlines())) or "(chưa có code)"
    user = (f"CHẾ ĐỘ: {mode}\nĐỀ BÀI:\n{statement or '(không có)'}\n\nNGÔN NGỮ: {LANG_NAME.get(language, language)}\n"
            f"CODE:\n{numbered}\n\nKẾT QUẢ CHẤM: {verdict or '(chưa nộp)'}\nTHÔNG BÁO LỖI:\n{error or '(không có)'}\n\n"
            f"CÂU HỎI CỦA BẠN HỌC: {question or '(không có)'}")
    return await complete(TUTOR_SYSTEM, user, max_tokens=1200)
