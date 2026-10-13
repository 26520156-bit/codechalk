"""Tạo mã VietQR (chuẩn EMVCo / NAPAS 247) có sẵn số tiền và nội dung chuyển khoản."""
from __future__ import annotations

import base64
import re
import struct
import unicodedata
import zlib

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for b in data.encode("utf-8"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def ascii_memo(text: str, limit: int = 25) -> str:
    """Nội dung chuyển khoản: bỏ dấu, chỉ giữ chữ, số, gạch dưới và khoảng trắng."""
    t = unicodedata.normalize("NFD", text).replace("đ", "d").replace("Đ", "D")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9_ ]", "", t)[:limit]


def payload(bank_bin: str, account: str, amount_vnd: int | None = None, memo: str = "") -> str:
    """Chuỗi dữ liệu VietQR. Có số tiền thì là mã động (12), không có là mã tĩnh (11)."""
    beneficiary = _tlv("00", bank_bin) + _tlv("01", account)
    merchant = _tlv("00", "A000000727") + _tlv("01", beneficiary) + _tlv("02", "QRIBFTTA")
    s = _tlv("00", "01") + _tlv("01", "12" if amount_vnd else "11") + _tlv("38", merchant) + _tlv("53", "704")
    if amount_vnd:
        s += _tlv("54", str(int(amount_vnd)))
    s += _tlv("58", "VN")
    if memo:
        s += _tlv("62", _tlv("08", ascii_memo(memo)))
    s += "6304"
    return s + crc16_ccitt(s)


def _png(matrix: list[list[bool]], box: int) -> bytes:
    """Mã hoá ma trận QR thành PNG đen trắng 1 bit (chỉ dùng thư viện chuẩn, không cần Pillow)."""
    size = len(matrix) * box
    raw = bytearray()
    for row in matrix:
        bits = "".join(("0" if dark else "1") * box for dark in row)        # 0 = đen, 1 = trắng
        bits += "0" * (-len(bits) % 8)
        line = b"\x00" + int(bits, 2).to_bytes(len(bits) // 8, "big")
        raw += line * box

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def png_data_uri(data: str, box: int = 8) -> str:
    q = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box, border=3)
    q.add_data(data)
    q.make(fit=True)
    return "data:image/png;base64," + base64.b64encode(_png(q.get_matrix(), box)).decode()