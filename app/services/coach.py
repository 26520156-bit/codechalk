"""Trợ lý AI cho CHALLENGE: gợi ý hướng làm, gợi ý code, chỉ lỗi, sửa lỗi giúp, code đáp án.

Code do AI viết (sửa lỗi, đáp án) luôn được chạy thử trên bộ test của bài trước khi trả về,
sai thì AI được sửa lại một lần với kết quả chạy thật. Đáp án đúng được lưu lại để dùng chung.
"""
from __future__ import annotations

import re

from ..models import Challenge
from . import ai, judge

MODES = ("HINT", "SUGGEST", "DEBUG", "EXPLAIN", "FIX", "SOLUTION")
FENCE = {"cpp": "cpp", "python": "python", "java": "java", "javascript": "javascript"}
ALIASES = {"cpp": {"cpp", "c++", "cc", "c"}, "python": {"python", "py", "python3"}, "java": {"java"},
           "javascript": {"javascript", "js", "node"}}

SYSTEM = """Bạn là Robot Trợ giảng của CodeChalk, kèm sinh viên năm nhất luyện lập trình. Trả lời bằng tiếng Việt, xưng "mình", gọi "bạn".
Nguyên tắc chung:
- Đọc kỹ đề, input/output mẫu và code (có đánh số dòng). Khi nói về lỗi luôn ghi rõ số dòng.
- Không bịa thông báo lỗi hay kết quả chạy. Kết quả chạy thật (nếu có) là căn cứ chính.
- Markdown gọn: tiêu đề ##, gạch đầu dòng, code trong khối ```."""

TASK = {
    "HINT": """NHIỆM VỤ: GỢI Ý HƯỚNG LÀM.
- Gợi ý theo 3 bậc: (1) nhận xét quan trọng về đề, (2) ý tưởng thuật toán, (3) các bước của khung giải bằng lời.
- KHÔNG viết code hoàn chỉnh. Tối đa 1 dòng code minh hoạ cú pháp nếu thật cần.""",
    "SUGGEST": """NHIỆM VỤ: GỢI Ý CODE.
- Dựa trên code hiện tại của bạn học (nếu có), viết ĐOẠN CODE TIẾP THEO hoặc khung chương trình bằng {lang}.
- Được viết code thật, nhưng phần lõi thuật toán quan trọng nhất để lại chú thích TODO kèm gợi ý cụ thể cần làm gì.
- Tối đa khoảng 25 dòng code, đặt trong một khối ```{fence}. Sau khối code, giải thích ngắn từng phần.""",
    "DEBUG": """NHIỆM VỤ: CHỈ RA VÌ SAO CODE SAI.
- Liệt kê từng lỗi: dòng nào, sai gì, vì sao gây ra kết quả chấm hiện tại, cách sửa bằng lời (có thể kèm 1–2 dòng code đã sửa).
- Nếu code đúng, nói rõ là đúng và chỉ ra trường hợp biên nên tự kiểm tra.""",
    "EXPLAIN": """NHIỆM VỤ: GIẢI THÍCH CODE.
- Giải thích code hiện tại làm gì theo từng khối dòng, độ phức tạp, và trả lời câu hỏi của bạn học nếu có.""",
    "FIX": """NHIỆM VỤ: SỬA LỖI GIÚP.
- Giữ nguyên cách làm, tên biến và bố cục của bạn học; chỉ sửa những chỗ sai, càng ít càng tốt.
- Nếu code trống hoặc không liên quan tới đề: nói rõ, KHÔNG tự viết lời giải mới, đề nghị dùng "Gợi ý code".
- Trả lời đúng khuôn sau:
## Lỗi tìm thấy
- **Dòng N**: sai gì → sửa thế nào (mỗi lỗi một gạch)
## Code đã sửa
```{fence}
(toàn bộ chương trình sau khi sửa, chạy được ngay)
```
## Ghi chú
(1–3 câu: cách tránh lỗi này lần sau)""",
    "SOLUTION": """NHIỆM VỤ: VIẾT CODE ĐÁP ÁN bằng {lang}.
- {io_rule}
- Ưu tiên lời giải rõ ràng, đúng với mọi input trong ràng buộc (chú ý tràn số, trường hợp biên), độ phức tạp hợp lý.
- C++: chuẩn C++17, chỉ thư viện chuẩn. Java: lớp public tên Main. Python: Python 3, thư viện chuẩn.
- Trả lời đúng khuôn sau:
## Ý tưởng
(2–5 câu)
## Độ phức tạp
Thời gian O(...), bộ nhớ O(...)
## Code
```{fence}
(chương trình hoàn chỉnh)
```
## Giải thích từng bước
(gạch đầu dòng ngắn, bám theo code)""",
}
IO_TESTED = "Chương trình hoàn chỉnh: đọc dữ liệu từ bàn phím (stdin) và in ra màn hình (stdout) ĐÚNG định dạng output của đề và test mẫu; không in thêm câu nhắc hay chữ thừa."
IO_FUNC = "Bài yêu cầu viết hàm/chương trình con: viết đúng hàm theo đề, kèm hàm main ngắn minh hoạ cách gọi."


def statement(c: Challenge) -> str:
    s = f"Bài {c.id} (chương {c.chapter}: {c.chapter_title}) — {c.title}\n{c.statement}"
    if c.input_format:
        s += f"\nINPUT: {c.input_format}"
    if c.output_format:
        s += f"\nOUTPUT: {c.output_format}"
    for i, smp in enumerate((c.samples or [])[:3], 1):
        s += f"\nVÍ DỤ {i}:\nInput:\n{smp.get('input', '')}\nOutput:\n{smp.get('output', '')}"
    s += f"\nGiới hạn: {c.time_limit_ms} ms, {c.memory_mb} MB."
    return s


def numbered(code: str) -> str:
    return "\n".join(f"{i + 1:>3}| {line}" for i, line in enumerate(code.splitlines())) or "(chưa có code)"


def extract_code(text: str, lang: str) -> tuple[str, str]:
    """Tách khối code của ngôn ngữ cần dùng khỏi câu trả lời. Trả về (code, phần chữ còn lại)."""
    blocks = list(re.finditer(r"```([\w+#-]*)[ \t]*\n([\s\S]*?)```", text or ""))
    if not blocks:
        return "", text or ""
    good = [b for b in blocks if b.group(1).lower() in ALIASES.get(lang, set())] or blocks
    best = max(good, key=lambda b: len(b.group(2)))
    rest = (text[:best.start()] + text[best.end():]).strip()
    rest = re.sub(r"\n## Code(?: đã sửa)?\s*\n(?=\n*##|\Z)", "\n", rest)   # bỏ tiêu đề mục code đã bị tách ra
    return best.group(2).rstrip() + "\n", rest


def tests_of(c: Challenge) -> list[dict]:
    if c.tests:
        return [{"input": t.input, "expected": t.expected_output, "sample": t.is_sample} for t in c.tests]
    return [{"input": s.get("input", ""), "expected": s.get("output", ""), "sample": True}
            for s in (c.samples or []) if s.get("output", "").strip()]


async def verify(c: Challenge, lang: str, code: str) -> dict | None:
    """Chạy code trên bộ test của bài. None nếu bài không có test để đối chiếu."""
    tests = tests_of(c)
    if not tests or not code.strip():
        return None
    r = await judge.judge(lang, code, tests, c.time_limit_ms, c.memory_mb)
    out = {"verdict": r.verdict, "passed": r.passed, "total": len(tests), "max_ms": r.max_ms, "ok": r.verdict == "AC",
           "tests": [x.get("v") for x in r.tests]}
    if r.verdict in ("CE", "SE"):
        out["compile"] = (r.compile or "")[:3000]
    bad = next((x for x in r.tests if x.get("v") not in ("AC", "OK")), None)
    if bad is not None:
        t = tests[bad["i"]]
        out["first_fail"] = {"i": bad["i"] + 1, "v": bad.get("v"), "sample": t["sample"], "why": bad.get("why", ""),
                             "stderr": (bad.get("stderr") or "")[-1200:]}
        if t["sample"]:
            out["first_fail"].update(input=t["input"][:600], expected=t["expected"][:600])
    return out


def _feedback(v: dict) -> str:
    """Mô tả kết quả chạy thật để AI tự sửa (test ẩn chỉ báo trạng thái, không lộ dữ liệu)."""
    if v.get("compile"):
        return "Code của bạn KHÔNG biên dịch được:\n" + v["compile"]
    f = v.get("first_fail") or {}
    s = f"Code của bạn chỉ đúng {v['passed']}/{v['total']} test. Test #{f.get('i')} bị {f.get('v')}"
    s += f" ({f['why']})" if f.get("why") else ""
    if f.get("sample"):
        s += f".\nInput:\n{f.get('input')}\nOutput mong đợi:\n{f.get('expected')}"
    else:
        s += " (test ẩn: kiểm tra trường hợp biên, số lớn/tràn số, định dạng in ra, thời gian chạy)."
    if f.get("stderr"):
        s += "\nThông báo lỗi khi chạy:\n" + f["stderr"]
    return s


async def ask(mode: str, c: Challenge, lang: str, code: str, question: str = "", verdict: str = "", error: str = "") -> dict:
    """Gọi AI theo chế độ. Với FIX/SOLUTION: tách code, chạy thử trên test, sai thì cho AI sửa lại một lần."""
    fence = FENCE.get(lang, "")
    task = TASK[mode].format(lang=ai.LANG_NAME.get(lang, lang), fence=fence,
                             io_rule=IO_TESTED if (c.has_tests or tests_of(c)) else IO_FUNC)
    prompt = (f"{task}\n\nĐỀ BÀI:\n{statement(c)}\n\nNGÔN NGỮ: {ai.LANG_NAME.get(lang, lang)}\n")
    if mode != "SOLUTION":
        prompt += (f"\nCODE CỦA BẠN HỌC (có số dòng):\n{numbered(code)}\n\nKẾT QUẢ CHẤM GẦN NHẤT: {verdict or '(chưa chạy)'}\n"
                   f"THÔNG BÁO LỖI:\n{error or '(không có)'}\n")
    if question:
        prompt += f"\nCÂU HỎI CỦA BẠN HỌC: {question}\n"
    big = mode in ("FIX", "SOLUTION")
    text = await ai.complete(SYSTEM, prompt, max_tokens=3500 if big else 1500)
    if not big:
        return {"text": text, "code": "", "verify": None, "attempts": 1}

    code_out, rest = extract_code(text, lang)
    if not code_out:
        return {"text": text, "code": "", "verify": None, "attempts": 1}
    v = await verify(c, lang, code_out)
    attempts = 1
    if v is not None and not v["ok"]:
        retry = (prompt + f"\n\nBẢN TRẢ LỜI TRƯỚC CỦA BẠN:\n{text}\n\nKẾT QUẢ CHẠY THẬT TRÊN MÁY CHẤM:\n{_feedback(v)}\n\n"
                 "Hãy sửa lại cho đúng và trả lời lại đầy đủ theo đúng khuôn ở trên.")
        try:
            text2 = await ai.complete(SYSTEM, retry, max_tokens=3500)
            code2, rest2 = extract_code(text2, lang)
            if code2:
                v2 = await verify(c, lang, code2)
                attempts = 2
                if v2 is not None and v2["passed"] >= v["passed"]:
                    code_out, rest, v = code2, rest2, v2
        except ai.AIUnavailable:
            pass
    return {"text": rest, "code": code_out, "verify": v, "attempts": attempts}
