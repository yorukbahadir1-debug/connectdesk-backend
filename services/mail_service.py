import os
import random
import smtplib
import ssl
from email.message import EmailMessage


def generate_reset_code() -> str:
    return f"{random.randint(100000, 999999)}"


def send_password_reset_code(to_email: str, code: str) -> bool:
    smtp_email = (os.getenv("SMTP_EMAIL") or os.getenv("SMTP_USER") or os.getenv("SMTP_FROM") or "").strip()
    smtp_password = (os.getenv("SMTP_APP_PASSWORD") or os.getenv("SMTP_PASSWORD") or "").strip()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_from = (os.getenv("SMTP_FROM") or smtp_email).strip()
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "ConnectDesk").strip()
    use_ssl = os.getenv("SMTP_USE_SSL", "").lower().strip()

    if not smtp_email or not smtp_password:
        return False

    msg = EmailMessage()
    msg["Subject"] = "ConnectDesk şifre yenileme kodu"
    msg["From"] = f"{smtp_from_name} <{smtp_from}>"
    msg["To"] = to_email
    msg.set_content(
        "ConnectDesk şifre yenileme kodunuz:\n\n"
        f"{code}\n\n"
        "Bu kod 15 dakika geçerlidir. Bu işlemi siz başlatmadıysanız bu mesajı dikkate almayın."
    )

    if use_ssl == "true" or smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context(), timeout=30) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(smtp_email, smtp_password)
            server.send_message(msg)

    return True
