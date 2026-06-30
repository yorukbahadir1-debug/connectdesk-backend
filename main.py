import os
import time
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from services.firebase_service import (
    create_user, login_user, get_user, create_contact, update_contact_details,
    update_contact_note, update_contact_profile_image, list_contacts, get_contact,
    delete_contact as fb_delete_contact, list_contact_files, save_file_record,
    delete_file_record_by_google_id, get_user_drive_status, save_password_reset_code,
    verify_password_reset_code, mark_password_reset_code_used, update_user_password_by_email,
    get_user_backup_settings, set_backup_enabled, save_recovery_backup_record,
    list_user_file_records
)
from services.drive_service import (
    create_google_auth_url, finish_google_callback, get_or_create_contact_folder,
    upload_file_to_folder, replace_file_content, delete_drive_file
)
from services.mail_service import generate_reset_code, send_password_reset_code
from services.crypto_service import hash_backup_password, verify_backup_password
from services.backup_service import upload_encrypted_recovery_backup, decrypt_recovery_backup_text
from services.backup_drive_service import get_latest_recovery_file, download_recovery_file_text

app = FastAPI(title="ConnectDesk Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://turkishotguns.com", "https://www.turkishotguns.com",
        "http://turkishotguns.com", "http://www.turkishotguns.com",
        "http://localhost:3000", "http://127.0.0.1:5500", "null"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESET_TTL_SECONDS = int(os.getenv("RESET_TTL_SECONDS", "900"))
TEMP_DIR = Path(os.getenv("TEMP_UPLOAD_DIR", "temp_uploads"))
TEMP_DIR.mkdir(exist_ok=True)

class AuthJSON(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4)

class ForgotJSON(BaseModel):
    email: EmailStr

class VerifyCodeJSON(BaseModel):
    email: EmailStr
    code: str

class ResetJSON(BaseModel):
    email: EmailStr
    code: str
    new_password: str = Field(min_length=4)

class ContactJSON(BaseModel):
    user_id: str
    name: str
    phone: str = ""
    note: str = ""
    email: str = ""
    company: str = ""
    drive: str = ""


def _email(value: str) -> str:
    return str(value or "").strip().lower()


def _save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.bin").suffix
    fd, path = tempfile.mkstemp(prefix="connectdesk_", suffix=suffix, dir=str(TEMP_DIR))
    os.close(fd)
    with open(path, "wb") as f:
        f.write(upload.file.read())
    return path


def _public_contact(data: dict) -> dict:
    return data or {}

@app.get("/")
def root():
    return {"ok": True, "service": "ConnectDesk Backend", "version": "2.0.0"}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/register")
def register_form(email: str = Form(...), password: str = Form(...)):
    user = create_user(_email(email), password)
    if not user:
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı.")
    return {"ok": True, "message": "Hesap oluşturuldu.", "user": user, **user}

@app.post("/auth/register")
def register_json(payload: AuthJSON):
    return register_form(str(payload.email), payload.password)

@app.post("/login")
def login_form(email: str = Form(...), password: str = Form(...)):
    user = login_user(_email(email), password)
    if not user:
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı.")
    return {"ok": True, "message": "Giriş başarılı.", "user": user, **user}

@app.post("/auth/login")
def login_json(payload: AuthJSON):
    return login_form(str(payload.email), payload.password)

@app.get("/users/{user_id}/contacts")
def contacts(user_id: str):
    return {"ok": True, "contacts": [_public_contact(c) for c in list_contacts(user_id)]}

@app.post("/contacts")
def add_contact(
    user_id: str = Form(...), name: str = Form(...), phone: str = Form(""), note: str = Form(""),
    email: str = Form(""), company: str = Form(""), drive: str = Form("")
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Ad soyad boş olamaz.")
    contact = create_contact(user_id=user_id, name=name, phone=phone, note=note, email=email, company=company, drive=drive)
    return {"ok": True, "contact": contact, **contact}

@app.post("/contacts/json")
def add_contact_json(payload: ContactJSON):
    return add_contact(payload.user_id, payload.name, payload.phone, payload.note, payload.email, payload.company, payload.drive)

@app.put("/contacts/{contact_id}")
def update_contact(
    contact_id: str, name: str = Form(...), phone: str = Form(""), email: str = Form(""),
    company: str = Form(""), drive: str = Form("")
):
    contact = update_contact_details(contact_id, name, phone, email, company, drive)
    if not contact:
        raise HTTPException(status_code=404, detail="Kişi bulunamadı.")
    return {"ok": True, "contact": contact, **contact}

@app.put("/contacts/{contact_id}/note")
def update_note(contact_id: str, note: str = Form(...)):
    contact = update_contact_note(contact_id, note)
    if not contact:
        raise HTTPException(status_code=404, detail="Kişi bulunamadı.")
    return {"ok": True, "contact": contact, **contact}

@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: str):
    fb_delete_contact(contact_id)
    return {"ok": True}

@app.post("/contacts/{contact_id}/profile-image")
def upload_profile_image(contact_id: str, file: UploadFile = File(...)):
    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Kişi bulunamadı.")
    user_id = contact.get("user_id")
    path = _save_upload(file)
    try:
        folder_id = contact.get("google_folder_id") or get_or_create_contact_folder(user_id, contact.get("name", "Kişi"), contact_id)
        uploaded = upload_file_to_folder(user_id, path, folder_id)
        updated = update_contact_profile_image(contact_id, uploaded)
        return {"ok": True, "contact": updated, "file": uploaded}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Profil resmi yüklenemedi: {exc}")
    finally:
        try: os.remove(path)
        except Exception: pass

@app.get("/contacts/{contact_id}/files")
def contact_files(contact_id: str):
    return {"ok": True, "files": list_contact_files(contact_id)}

@app.post("/contacts/{contact_id}/files/upload")
def upload_contact_file(contact_id: str, backup_password: str = Form(""), file: UploadFile = File(...)):
    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Kişi bulunamadı.")
    user_id = contact.get("user_id")
    path = _save_upload(file)
    try:
        folder_id = contact.get("google_folder_id") or get_or_create_contact_folder(user_id, contact.get("name", "Kişi"), contact_id)
        uploaded = upload_file_to_folder(user_id, path, folder_id)
        record = save_file_record(contact_id, uploaded.get("id", ""), uploaded.get("name", file.filename or ""), uploaded.get("mimeType", ""), uploaded.get("webViewLink", ""), uploaded.get("webContentLink", ""))
        return {"ok": True, "file": record, "drive_file": uploaded, **record}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Dosya yüklenemedi: {exc}")
    finally:
        try: os.remove(path)
        except Exception: pass

@app.put("/files/{google_file_id}/replace")
def replace_file(google_file_id: str, file: UploadFile = File(...)):
    path = _save_upload(file)
    try:
        # user_id bilinmediğinde Drive service token bulamayabilir; mevcut EXE akışında google_file_id üzerinden record bulunur.
        from services.firebase_service import get_file_record_by_any_google_id, get_contact
        record = get_file_record_by_any_google_id(google_file_id)
        if not record:
            raise HTTPException(status_code=404, detail="Dosya kaydı bulunamadı.")
        contact = get_contact(record.get("contact_id"))
        result = replace_file_content(contact.get("user_id"), google_file_id, path)
        return {"ok": True, "file": result}
    finally:
        try: os.remove(path)
        except Exception: pass

@app.delete("/files/{google_file_id}")
def delete_file(google_file_id: str):
    from services.firebase_service import get_file_record_by_any_google_id, get_contact
    record = get_file_record_by_any_google_id(google_file_id)
    if record:
        contact = get_contact(record.get("contact_id"))
        if contact:
            try: delete_drive_file(contact.get("user_id"), google_file_id)
            except Exception: pass
    delete_file_record_by_google_id(google_file_id)
    return {"ok": True}

@app.get("/users/{user_id}/drive/status")
def drive_status(user_id: str):
    return {"ok": True, **get_user_drive_status(user_id)}

@app.get("/users/{user_id}/drive/auth-url")
def drive_auth(user_id: str):
    return {"ok": True, "auth_url": create_google_auth_url(user_id)}

@app.get("/google/callback")
def google_callback(request: Request, state: str = ""):
    try:
        result = finish_google_callback(str(request.url), state)
        ok = True
        title = "Google Drive bağlantısı tamamlandı"
        message = "ConnectDesk hesabınız Google Drive ile bağlandı. Bu sekmeyi kapatıp ana uygulamaya dönebilirsiniz."
        detail = result
    except Exception as exc:
        ok = False
        title = "Google Drive bağlantısı tamamlanamadı"
        message = "Bağlantı sırasında hata oluştu. Ana uygulamaya dönüp tekrar deneyin."
        detail = {"error": str(exc)}

    status_text = "Başarılı" if ok else "Hata"
    accent = "#d4952f" if ok else "#ef4444"
    return HTMLResponse(f"""
    <!doctype html>
    <html lang="tr">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>ConnectDesk Drive Bağlantısı</title>
      <style>
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          min-height: 100vh;
          display: grid;
          place-items: center;
          background: radial-gradient(circle at top left, #142033 0, #05080d 42%, #02040a 100%);
          color: #f8fafc;
          font-family: Arial, sans-serif;
          padding: 24px;
        }}
        .card {{
          width: min(720px, 100%);
          border: 1px solid rgba(255,255,255,.14);
          background: #111821;
          border-radius: 22px;
          padding: 34px;
          box-shadow: 0 30px 90px rgba(0,0,0,.45);
        }}
        .brand {{ display:flex; align-items:center; gap:16px; margin-bottom:24px; }}
        .mark {{ width:58px; height:58px; border-radius:14px; display:grid; place-items:center; background:#182538; color:#ffd88a; font-size:34px; font-weight:900; border:1px solid rgba(212,149,47,.45); }}
        h1 {{ margin:0; font-size:34px; }}
        p {{ color:#cbd5e1; line-height:1.55; font-size:17px; }}
        .status {{ display:inline-block; margin:12px 0 18px; padding:8px 12px; border-radius:999px; background:{accent}; color:#090909; font-weight:900; }}
        .buttons {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:22px; }}
        button, a {{ border:0; border-radius:12px; padding:14px 18px; font-weight:900; cursor:pointer; text-decoration:none; }}
        button {{ background:{accent}; color:#090909; }}
        a {{ background:#263445; color:#f8fafc; }}
        pre {{ white-space:pre-wrap; word-break:break-word; max-height:170px; overflow:auto; background:#070c13; color:#94a3b8; padding:14px; border-radius:12px; border:1px solid rgba(255,255,255,.08); }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="brand"><div class="mark">C</div><div><h1>ConnectDesk</h1><p>Google Drive bağlantısı</p></div></div>
        <span class="status">{status_text}</span>
        <h1>{title}</h1>
        <p>{message}</p>
        <div class="buttons">
          <button onclick="window.close()">Sekmeyi Kapat</button>
          <a href="https://turkishotguns.com/index.html" target="_self">Uygulamaya Dön</a>
        </div>
        <pre>{detail}</pre>
      </div>
      <script>
        try {{ if (window.opener) {{ window.opener.postMessage({{type:'CONNECTDESK_DRIVE_CONNECTED'}}, '*'); }} }} catch(e) {{}}
      </script>
    </body>
    </html>
    """)

@app.post("/forgot-password/request-code")
def forgot_request_form(email: str = Form(...)):
    email = _email(email)
    if not get_user(email):
        raise HTTPException(status_code=404, detail="Bu e-posta ile kayıtlı kullanıcı yok.")
    code = generate_reset_code()
    save_password_reset_code(email, code, int(time.time()) + RESET_TTL_SECONDS)
    sent = send_password_reset_code(email, code)
    if not sent:
        raise HTTPException(status_code=500, detail="SMTP ayarları eksik veya mail gönderilemedi.")
    return {"ok": True, "message": "Doğrulama kodu gönderildi."}

@app.post("/forgot-password/send-code")
def forgot_send_json(payload: ForgotJSON):
    return forgot_request_form(str(payload.email))

@app.post("/forgot-password/verify-code")
def forgot_verify_form(email: str = Form(...), code: str = Form(...)):
    ok = verify_password_reset_code(_email(email), str(code).strip(), int(time.time()))
    if not ok:
        raise HTTPException(status_code=400, detail="Doğrulama kodu hatalı veya süresi dolmuş.")
    return {"ok": True, "message": "Kod doğrulandı."}

@app.post("/forgot-password/verify-code-json")
def forgot_verify_json(payload: VerifyCodeJSON):
    return forgot_verify_form(str(payload.email), payload.code)

@app.post("/forgot-password/reset")
async def forgot_reset(request: Request):
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        body = await request.json()
        email = body.get("email", "")
        code = body.get("code", "")
        new_password = body.get("new_password", "")
    else:
        form = await request.form()
        email = form.get("email", "")
        code = form.get("code", "")
        new_password = form.get("new_password", "")
    email = _email(email)
    if len(str(new_password)) < 4:
        raise HTTPException(status_code=400, detail="Şifre en az 4 karakter olmalıdır.")
    if not verify_password_reset_code(email, str(code).strip(), int(time.time())):
        raise HTTPException(status_code=400, detail="Doğrulama kodu hatalı veya süresi dolmuş.")
    if not update_user_password_by_email(email, str(new_password)):
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    mark_password_reset_code_used(email)
    return {"ok": True, "message": "Şifre güncellendi."}

@app.get("/recovery", response_class=HTMLResponse)
def recovery_page():
    return """
    <!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ConnectDesk Kurtarma</title>
    <style>body{margin:0;background:#07111f;color:#f8fafc;font-family:Arial;padding:40px}.card{max-width:900px;margin:auto;background:#0d1b2e;border:1px solid #1e4775;border-radius:18px;padding:28px}input{width:100%;padding:14px;margin:8px 0 16px;background:#06101d;color:#fff;border:1px solid #31527a;border-radius:10px}button{padding:14px 22px;border:0;border-radius:10px;background:#2f7ee6;color:#fff;font-weight:800}.msg{margin-top:16px;white-space:pre-wrap}</style></head><body><div class='card'><h1>ConnectDesk Kurtarma</h1><p>Yedekleme şifresiyle son kurtarma yedeğini çözmek için kullanılır.</p><label>Kullanıcı e-posta adresi</label><input id='email' placeholder='ornek@mail.com'><label>Yedekleme şifresi</label><input id='password' type='password' placeholder='Yedekleme şifren'><button onclick='openBackup()'>Yedeği Aç</button><div id='msg' class='msg'></div></div><script>async function openBackup(){let msg=document.getElementById('msg');msg.textContent='Kontrol ediliyor...';try{let r=await fetch('/recovery/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.value,backup_password:password.value})});let d=await r.json();if(!r.ok)throw new Error(d.detail||'İşlem başarısız');msg.textContent=JSON.stringify(d.data,null,2)}catch(e){msg.textContent=e.message}}</script></body></html>
    """

class RecoveryOpen(BaseModel):
    email: EmailStr
    backup_password: str

@app.post("/recovery/open")
def recovery_open(payload: RecoveryOpen):
    user = get_user(str(payload.email).lower())
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    latest = get_latest_recovery_file(user["id"])
    if not latest:
        raise HTTPException(status_code=404, detail="Kurtarma yedeği bulunamadı.")
    text = download_recovery_file_text(latest["id"])
    data = decrypt_recovery_backup_text(text, payload.backup_password)
    return {"ok": True, "file": latest, "data": data}

@app.get("/users/{user_id}/backup/status")
def backup_status(user_id: str):
    return {"ok": True, **get_user_backup_settings(user_id)}

@app.post("/users/{user_id}/backup/enable")
def backup_enable(user_id: str, backup_password: str = Form(...)):
    if len(backup_password) < 4:
        raise HTTPException(status_code=400, detail="Yedek şifresi en az 4 karakter olmalı.")
    user = set_backup_enabled(user_id, True, hash_backup_password(backup_password))
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    return {"ok": True, "backup_enabled": True}

@app.post("/users/{user_id}/backup/disable")
def backup_disable(user_id: str):
    user = set_backup_enabled(user_id, False)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    return {"ok": True, "backup_enabled": False}

@app.post("/users/{user_id}/backup/recovery/create")
def backup_create(user_id: str, backup_password: str = Form(...)):
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    contacts = list_contacts(user_id)
    files = list_user_file_records(user_id)
    uploaded = upload_encrypted_recovery_backup(user, contacts, files, backup_password)
    save_recovery_backup_record(user_id, uploaded.get("id", ""), uploaded.get("name", ""))
    return {"ok": True, "backup": uploaded}

@app.post("/users/{user_id}/backup/change-password")
def backup_change_password(user_id: str, old_backup_password: str = Form(...), new_backup_password: str = Form(...), new_backup_password_repeat: str = Form(...)):
    if new_backup_password != new_backup_password_repeat:
        raise HTTPException(status_code=400, detail="Yeni yedek şifreleri eşleşmiyor.")
    settings = get_user_backup_settings(user_id)
    if settings.get("backup_password_hash") and not verify_backup_password(old_backup_password, settings["backup_password_hash"]):
        raise HTTPException(status_code=400, detail="Eski yedek şifresi hatalı.")
    set_backup_enabled(user_id, True, hash_backup_password(new_backup_password))
    return {"ok": True, "message": "Yedek şifresi güncellendi."}
