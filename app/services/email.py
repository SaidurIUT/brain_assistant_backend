from email.message import EmailMessage
import smtplib
from urllib.parse import urlencode

from app.core.config import settings


def frontend_url(path: str, **query: str) -> str:
    base = settings.frontend_base_url.rstrip("/")
    if not query:
        return f"{base}{path}"
    return f"{base}{path}?{urlencode(query)}"


def send_email(*, to_email: str, subject: str, text_body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)

    smtp_cls = smtplib.SMTP_SSL if settings.smtp_use_tls else smtplib.SMTP
    with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
