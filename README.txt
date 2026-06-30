ConnectDesk gerçek şifre sıfırlama backend paketi

Render ayarları:
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT

Environment Variables:
SMTP_HOST=mail.turkishotguns.com
SMTP_PORT=465
SMTP_USER=info@turkishotguns.com
SMTP_PASSWORD=mail hesabının şifresi
SMTP_FROM=info@turkishotguns.com
SMTP_FROM_NAME=ConnectDesk
SMTP_USE_SSL=true
RESET_CODE_SECRET=rastgele-uzun-bir-yazi

Endpointler:
POST /auth/register
POST /auth/login
POST /forgot-password/send-code
POST /forgot-password/reset

Not: SMTP kullanıcı adı/şifresi doğru değilse kod maili gönderilemez. Bu güvenlik gereği mecburidir.
