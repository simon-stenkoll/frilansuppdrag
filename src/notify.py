"""Emails the day's new assignments over SMTP.

Only assignments flagged is_new are included. Config/SMTP failures are logged
and swallowed so a notification problem never breaks the pipeline.

Required env vars (see README): SMTP_USER, SMTP_PASSWORD. SMTP_HOST, SMTP_PORT,
EMAIL_FROM and EMAIL_TO are optional and fall back to the values in config.py.
For Gmail, SMTP_PASSWORD must be an app password, not the account password.
"""

import os
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from html import escape

from src.config import (
    EMAIL_FROM_ENV,
    EMAIL_MAX_ITEMS,
    EMAIL_SUBJECT_PREFIX,
    EMAIL_TO,
    EMAIL_TO_ENV,
    NOTIFY_WHEN_EMPTY,
    REQUEST_TIMEOUT,
    SMTP_HOST_DEFAULT,
    SMTP_HOST_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_PORT_DEFAULT,
    SMTP_PORT_ENV,
    SMTP_USER_ENV,
)
from src.models import Assignment

# Score bucket colors (match the digest's)
_COLOR_HIGH = "#1f9d55"  # green  (>=7)
_COLOR_MID = "#b7791f"   # amber  (4-6)
_COLOR_LOW = "#c53030"   # red    (1-3)
_COLOR_NONE = "#6b7280"  # gray   (not scored)


class _SmtpConfig:
    """Resolved SMTP settings; `ok` is False when credentials are missing."""

    def __init__(self) -> None:
        self.host = os.environ.get(SMTP_HOST_ENV) or SMTP_HOST_DEFAULT
        self.port = int(os.environ.get(SMTP_PORT_ENV) or SMTP_PORT_DEFAULT)
        self.user = os.environ.get(SMTP_USER_ENV, "")
        self.password = os.environ.get(SMTP_PASSWORD_ENV, "")
        self.sender = os.environ.get(EMAIL_FROM_ENV) or self.user
        self.recipient = os.environ.get(EMAIL_TO_ENV) or EMAIL_TO

    @property
    def ok(self) -> bool:
        return bool(self.user and self.password and self.recipient)


def _color(score: int) -> str:
    if score >= 7:
        return _COLOR_HIGH
    if score >= 4:
        return _COLOR_MID
    if score >= 1:
        return _COLOR_LOW
    return _COLOR_NONE


def _score_text(score: int) -> str:
    return f"{score}/10" if score else "–"


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _card_html(a: Assignment) -> str:
    """One assignment as a table row (tables survive every mail client)."""
    meta_parts = [p for p in (a.company, a.location, a.source) if p]
    summary = _truncate(a.summary or a.description or "", 400)
    summary_html = (
        f'<div style="color:#374151;font-size:14px;line-height:1.5;margin-top:6px">'
        f"{escape(summary)}</div>"
        if summary
        else ""
    )

    return f"""<tr>
  <td style="padding:14px 16px;border:1px solid #e5e7eb;border-radius:8px;background:#ffffff">
    <div>
      <a href="{escape(a.url, quote=True)}"
         style="color:#111827;font-size:16px;font-weight:600;text-decoration:none">{escape(a.title or "(utan titel)")}</a>
      <span style="color:{_color(a.relevance_score)};font-size:13px;font-weight:700;white-space:nowrap;margin-left:8px">{_score_text(a.relevance_score)}</span>
    </div>
    <div style="color:#6b7280;font-size:13px;margin-top:4px">{escape(" · ".join(meta_parts))}</div>
    {summary_html}
  </td>
</tr>
<tr><td style="height:10px;line-height:10px">&nbsp;</td></tr>"""


def _build_html(new: list[Assignment], today: str, page_url: str, warning: str) -> str:
    warning_html = (
        f'<div style="background:#fffbeb;border:1px solid #fcd34d;color:#92400e;'
        f'border-radius:8px;padding:12px 14px;font-size:14px;margin-bottom:18px">'
        f"&#9888;&#65039; {escape(warning)}</div>"
        if warning
        else ""
    )
    page_link = (
        f'<p style="font-size:13px;color:#6b7280;margin:18px 0 0">'
        f'Hela digesten: <a href="{escape(page_url, quote=True)}" style="color:#4f46e5">{escape(page_url)}</a></p>'
        if page_url
        else ""
    )

    if new:
        shown = new[:EMAIL_MAX_ITEMS]
        rows = "\n".join(_card_html(a) for a in shown)
        overflow = (
            f'<p style="font-size:13px;color:#6b7280">… och {len(new) - len(shown)} till '
            f"(se hela digesten).</p>"
            if len(new) > len(shown)
            else ""
        )
        heading = f"&#128203; Dagens nya konsultuppdrag ({len(new)} st)"
        body = f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">\n{rows}\n</table>{overflow}'
    else:
        heading = "&#128203; Inga nya konsultuppdrag idag"
        body = '<p style="color:#6b7280;font-size:14px">Inget nytt dök upp i dagens körning.</p>'

    return f"""<!DOCTYPE html>
<html lang="sv">
<body style="margin:0;padding:24px 12px;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif">
  <div style="max-width:640px;margin:0 auto">
    <h1 style="font-size:18px;color:#111827;margin:0 0 4px">{heading}</h1>
    <div style="color:#6b7280;font-size:13px;margin-bottom:18px">Stockholm &middot; Data Engineering / BI / Analytics &middot; {escape(today)}</div>
    {warning_html}
    {body}
    {page_link}
  </div>
</body>
</html>"""


def _build_text(new: list[Assignment], today: str, page_url: str, warning: str) -> str:
    lines = []
    if warning:
        lines.append(f"VARNING: {warning}\n")
    if new:
        lines.append(f"Dagens nya konsultuppdrag ({len(new)} st) — {today}\n")
        for a in new[:EMAIL_MAX_ITEMS]:
            meta = " · ".join(p for p in (a.company, a.location, a.source) if p)
            lines.append(f"[{_score_text(a.relevance_score)}] {a.title}")
            lines.append(f"  {meta}")
            lines.append(f"  {a.url}\n")
        if len(new) > EMAIL_MAX_ITEMS:
            lines.append(f"… och {len(new) - EMAIL_MAX_ITEMS} till (se hela digesten).\n")
    else:
        lines.append(f"Inga nya konsultuppdrag idag — {today}\n")
    if page_url:
        lines.append(f"Hela digesten: {page_url}")
    return "\n".join(lines)


def _send(cfg: _SmtpConfig, subject: str, html: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if cfg.port == 465:
        with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=REQUEST_TIMEOUT, context=context) as server:
            server.login(cfg.user, cfg.password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=REQUEST_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(cfg.user, cfg.password)
            server.send_message(msg)


def send_email(assignments: list[Assignment], page_url: str = "", warning: str = "") -> None:
    """Email the new assignments. Safe to call unconditionally."""
    cfg = _SmtpConfig()
    if not cfg.ok:
        print(
            f"[notify] {SMTP_USER_ENV}/{SMTP_PASSWORD_ENV} not set — skipping email notification"
        )
        return

    new = [a for a in assignments if a.is_new]
    if not new and not NOTIFY_WHEN_EMPTY:
        print("[notify] No new assignments — nothing sent")
        return

    # Sort highest-scoring first so the most relevant appear at the top.
    new.sort(key=lambda x: x.relevance_score, reverse=True)
    today = date.today().isoformat()
    subject = (
        f"{EMAIL_SUBJECT_PREFIX} {today}: {len(new)} nya uppdrag"
        if new
        else f"{EMAIL_SUBJECT_PREFIX} {today}: inga nya uppdrag"
    )

    try:
        _send(
            cfg,
            subject,
            _build_html(new, today, page_url, warning),
            _build_text(new, today, page_url, warning),
        )
        print(f"[notify] Emailed {len(new)} new assignments to {cfg.recipient}")
    except (smtplib.SMTPException, OSError) as e:
        print(f"[notify] Email notification failed: {type(e).__name__}: {e}")


def send_failure_email(message: str) -> None:
    """Send a short failure alert — used by the workflow when a run breaks."""
    cfg = _SmtpConfig()
    if not cfg.ok:
        print(f"[notify] {SMTP_USER_ENV}/{SMTP_PASSWORD_ENV} not set — skipping failure email")
        return

    today = date.today().isoformat()
    text = f"Daily Contract Digest misslyckades.\n\n{message}"
    html = (
        '<body style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Arial,sans-serif">'
        '<p style="font-size:15px;color:#111827">&#9888;&#65039; Daily Contract Digest misslyckades.</p>'
        f'<p style="font-size:14px;color:#374151">{escape(message)}</p></body>'
    )
    try:
        _send(cfg, f"{EMAIL_SUBJECT_PREFIX} {today}: KÖRNINGEN MISSLYCKADES", html, text)
        print(f"[notify] Emailed failure alert to {cfg.recipient}")
    except (smtplib.SMTPException, OSError) as e:
        print(f"[notify] Failure email could not be sent: {type(e).__name__}: {e}")


if __name__ == "__main__":  # python -m src.notify --failure "<message>"
    import sys

    if len(sys.argv) > 2 and sys.argv[1] == "--failure":
        send_failure_email(sys.argv[2])
    else:
        print("usage: python -m src.notify --failure <message>")
