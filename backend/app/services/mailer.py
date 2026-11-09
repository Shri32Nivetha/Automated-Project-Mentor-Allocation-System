"""Optional SMTP delivery. Does nothing (and says so) when SMTP is not configured."""
import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings

log = logging.getLogger("mailer")


def send_email(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    if not s.email_enabled:
        log.info("E-mail not sent (SMTP not configured): subject=%r", subject)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        log.exception("E-mail delivery failed")
        return False
