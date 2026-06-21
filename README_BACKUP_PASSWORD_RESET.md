# ConnectDesk Backend - Yedekleme ve Şifremi Unuttum

Eklenen endpointler:

## Yedekleme
- POST `/users/{user_id}/backup/enable`
- POST `/users/{user_id}/backup/disable`
- GET `/users/{user_id}/backup/status`
- POST `/users/{user_id}/backup/recovery/create`

## Şifremi Unuttum
- POST `/forgot-password/request-code`
- POST `/forgot-password/verify-code`
- POST `/forgot-password/reset`

## Dosya Yedekleme
`/contacts/{contact_id}/files/upload` artık dosyayı iki yere yükler:
1. Asıl kişi klasörü
2. Kişinin `__BACKUP__` klasörü

Firebase `contact_files` kaydına hem `google_file_id` hem `backup_google_file_id` yazılır.

## Mail Ayarları
`.env` içine şunları ekleyin:

```env
SMTP_EMAIL=mail@gmail.com
SMTP_APP_PASSWORD=gmail_app_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

SMTP ayarı yapılmazsa `/forgot-password/request-code` cevabında test için `dev_code` döner.
