"""Отправка писем (SMTP): подтверждение почты при регистрации.

Настройки — в .env: SMTP_HOST, SMTP_PORT (587 — STARTTLS, 465 — SSL), SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
DREAMGOODS_PUBLIC_URL — адрес сайта для ссылок в письмах (иначе берётся адрес, с которого пришёл запрос).
Если почта не настроена, письмо не отправляется: ссылка пишется в журнал сервера, а мастер может подтвердить
почту пользователя вручную («Пользователи» → «подтвердить почту»).
"""
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import config
from .logs import log

HOST = config.env("SMTP_HOST", "")
PORT = int(config.env("SMTP_PORT", "587") or 587)
USER = config.env("SMTP_USER", "")
PASSWORD = config.env("SMTP_PASSWORD", "")
FROM = config.env("SMTP_FROM", "") or USER
PUBLIC_URL = config.app_env("PUBLIC_URL", "").rstrip("/")


def configured():
    return bool(HOST and FROM)


def _send(to, subject, text, html):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("DreamGoods", FROM))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=(FROM.split("@")[-1] or "dreamgoods"))
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    if PORT == 465:
        with smtplib.SMTP_SSL(HOST, PORT, context=ctx, timeout=30) as s:
            if USER:
                s.login(USER, PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(HOST, PORT, timeout=30) as s:
            s.ehlo()
            if s.has_extn("starttls"):
                s.starttls(context=ctx)
                s.ehlo()
            if USER:
                s.login(USER, PASSWORD)
            s.send_message(msg)


def send(to, subject, text, html="", log_link=""):
    """Отправка в фоне (запрос не ждёт почтовый сервер). Без настроек почты — ссылка в журнал."""
    if not configured():
        log.warning("Письмо для %s не отправлено — почта (SMTP) не настроена в .env. %s", to,
                    f"Ссылка: {log_link}" if log_link else "")
        return False

    def run():
        try:
            _send(to, subject, text, html)
            log.info("Письмо «%s» отправлено: %s", subject, to)
        except Exception as e:
            log.error("Письмо «%s» для %s не отправлено: %s", subject, to, e)

    threading.Thread(target=run, name="mailer", daemon=True).start()
    return True


def verify_email(to, name, link):
    text = (f"Здравствуйте{', ' + name if name else ''}!\n\n"
            f"Чтобы подтвердить почту и войти в DreamGoods, перейдите по ссылке:\n{link}\n\n"
            "Ссылка действует 48 часов. Если вы не регистрировались в DreamGoods, просто удалите это письмо.")
    html = (f"<p>Здравствуйте{', ' + name if name else ''}!</p>"
            f"<p>Чтобы подтвердить почту и войти в DreamGoods, нажмите кнопку:</p>"
            f'<p><a href="{link}" style="display:inline-block;padding:12px 22px;background:#6d3ff0;color:#fff;'
            f'border-radius:10px;text-decoration:none;font-weight:600">Подтвердить почту</a></p>'
            f'<p style="color:#777;font-size:13px">Или скопируйте ссылку: {link}<br>Ссылка действует 48 часов. '
            "Если вы не регистрировались в DreamGoods, просто удалите это письмо.</p>")
    return send(to, "Подтверждение почты — DreamGoods", text, html, log_link=link)
