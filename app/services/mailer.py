"""Gửi email qua SMTP (ví dụ Gmail: smtp.gmail.com:587 với Mật khẩu ứng dụng)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from ..config import settings

log = logging.getLogger("codechalk.mail")


def enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send(to: str, subject: str, text: str, link: str = "") -> bool:
    if not enabled():
        log.info("SMTP chưa cấu hình, bỏ qua email tới %s: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    url = (settings.public_url.rstrip("/") + link) if link.startswith("/") else link
    msg.set_content(text + (f"\n\nMở CodeChalk: {url}" if url else ""))
    msg.add_alternative(
        f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:auto;border:1px solid #e3e3e3;border-radius:12px;overflow:hidden">
<div style="background:#13201b;color:#f6cb5a;padding:14px 20px;font-weight:700;letter-spacing:.04em">CodeChalk</div>
<div style="padding:20px;color:#1b1b1b;line-height:1.55"><h2 style="margin:0 0 10px;font-size:18px">{escape(subject)}</h2>
<p style="white-space:pre-line;margin:0 0 16px">{escape(text)}</p>
{f'<a href="{escape(url)}" style="display:inline-block;background:#f6cb5a;color:#1b1b1b;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:600">Mở CodeChalk</a>' if url else ''}
</div></div>""", subtype="html")
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ssl.create_default_context(), timeout=20) as s:
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                if settings.smtp_tls:
                    s.starttls(context=ssl.create_default_context())
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.warning("Gửi email tới %s thất bại: %s", to, e)
        return False
