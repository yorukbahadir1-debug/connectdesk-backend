import os
import random
import smtplib
from email.message import EmailMessage


def generate_reset_code() -> str:
    return f"{random.randint(100000, 999999)}"


def send_password_reset_code(to_email: str, code: str) -> bool:
    smtp_email = os.getenv("SMTP_EMAIL", "").strip()
    smtp_password = os.getenv("SMTP_APP_PASSWORD", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_email or not smtp_password:
        # Development fallback: mail ayarı yoksa kod backend cevabında dönebilir.
        return False

    msg = EmailMessage()
    msg["Subject"] = "ConnectDesk sifre yenileme kodu"
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg.set_content(
        "ConnectDesk sifre yenileme kodunuz:\n\n"
        f"{code}\n\n"
        "Bu kodu siz istemediyseniz bu mesaji dikkate almayin."
    )

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)

    return True
