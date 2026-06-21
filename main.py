import os
from dotenv import load_dotenv

load_dotenv()
import shutil
import uuid
import json
import time

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from services.crypto_service import hash_backup_password, verify_backup_password
from services.backup_service import upload_encrypted_recovery_backup, backup_uploaded_file_for_contact, decrypt_recovery_backup_text, rotate_backup_password_for_all_files
from services.mail_service import generate_reset_code, send_password_reset_code

from services.firebase_service import (
    create_user,
    login_user,
    get_user,
    create_contact,
    update_contact_folder_id,
    update_contact_details,
    update_contact_note,
    update_contact_profile_image,
    list_contacts,
    get_contact,
    delete_contact,
    save_file_record,
    save_file_record_with_backup,
    delete_file_record_by_google_id,
    get_file_record_by_google_id,
    get_file_record_by_any_google_id,
    get_user_drive_status,
    set_backup_enabled,
    get_backup_status,
    get_user_backup_settings,
    save_file_record_recovery_backup,
    list_user_file_records,
    save_recovery_backup_record,
    save_password_reset_code,
    verify_password_reset_code,
    mark_password_reset_code_used,
    update_user_password_by_email
)

from services.drive_service import (
    create_google_auth_url,
    finish_google_callback,
    get_or_create_contact_folder,
    get_or_create_contact_backup_folder,
    get_or_create_user_recovery_folder,
    list_files_in_folder,
    upload_file_to_folder,
    upload_file_with_backup,
    upload_text_backup_file,
    delete_drive_file,
    replace_file_content,
    rename_drive_file,
    safe_drive_name
)


from services.backup_drive_service import get_latest_recovery_file, download_recovery_file_text, rename_contact_recovery_folder_if_exists

app = FastAPI(title="ConnectDesk API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "temp_uploads"

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)


def require_user(user_id: str):
    user_id = str(user_id).strip()
    user = get_user(user_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Kullanici bulunamadi."
        )

    return user


def require_contact(contact_id: str):
    contact_id = str(contact_id).strip()
    contact = get_contact(contact_id)

    if not contact:
        raise HTTPException(
            status_code=404,
            detail="Kisi bulunamadi."
        )

    return contact


def ensure_drive_connected(user_id: str):
    status = get_user_drive_status(user_id)

    if not status.get("connected"):
        raise HTTPException(
            status_code=400,
            detail="Google Drive bagli degil. Uygulamadaki 'Google Drive Bagla' butonuna basin."
        )

    return status


def get_or_create_folder_for_contact(contact: dict):
    user_id = str(contact.get("user_id", "")).strip()

    ensure_drive_connected(user_id)

    folder_id = str(contact.get("google_folder_id", "")).strip()

    if not folder_id:
        folder_id = get_or_create_contact_folder(
            user_id=user_id,
            contact_name=contact.get("name", "Kisi"),
            contact_id=contact["id"]
        )

        update_contact_folder_id(
            contact_id=contact["id"],
            google_folder_id=folder_id
        )

        contact["google_folder_id"] = folder_id

    return folder_id


def get_or_create_backup_folder_for_contact(contact: dict):
    user_id = str(contact.get("user_id", "")).strip()

    ensure_drive_connected(user_id)

    return get_or_create_contact_backup_folder(
        user_id=user_id,
        contact_name=contact.get("name", "Kisi"),
        contact_id=contact["id"]
    )


@app.get("/")
def home():
    return {
        "success": True,
        "message": "ConnectDesk API calisiyor",
        "version": "2.0.0",
        "drive_mode": "per_user_google_oauth"
    }


@app.get("/health")
def health():
    return {
        "success": True,
        "status": "ok"
    }


@app.get("/api/test")
def api_test():
    return {
        "success": True,
        "message": "API baglantisi basarili",
        "backend": "connectdesk-backend",
        "version": "2.0.0"
    }


@app.post("/register")
def register(
    email: str = Form(...),
    password: str = Form(...)
):
    user = create_user(email, password)

    if not user:
        raise HTTPException(
            status_code=400,
            detail="Bu e-posta zaten kayitli."
        )

    return {
        "success": True,
        "user": user
    }


@app.post("/login")
def login(
    email: str = Form(...),
    password: str = Form(...)
):
    user = login_user(email, password)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="E-posta veya sifre hatali."
        )

    return {
        "success": True,
        "user": user
    }


@app.get("/users/{user_id}/drive/status")
def drive_status(user_id: str):
    user = require_user(user_id)
    status = get_user_drive_status(user["id"])

    return {
        "success": True,
        "user_id": user["id"],
        "connected": bool(status.get("connected")),
        "drive_email": status.get("drive_email", ""),
        "drive_display_name": status.get("drive_display_name", ""),
        "drive_updated_at": status.get("drive_updated_at", "")
    }


@app.get("/users/{user_id}/drive/auth-url")
def drive_auth_url(user_id: str):
    user = require_user(user_id)

    try:
        auth_url = create_google_auth_url(user["id"])
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Google Drive baglanti linki olusturulamadi: {str(e)}"
        )

    return {
        "success": True,
        "auth_url": auth_url
    }


@app.get("/google/callback")
def google_callback(request: Request):
    try:
        state = str(request.query_params.get("state", "")).strip()
        result = finish_google_callback(str(request.url), state)

        drive_email = result.get("drive_email", "") or "Google Drive"

        return HTMLResponse(
            f"""
            <html>
                <head>
                    <title>ConnectDesk Google Drive</title>
                    <meta charset="utf-8">
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            background: #07111f;
                            color: #f5f7fb;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            min-height: 100vh;
                            margin: 0;
                        }}
                        .card {{
                            background: #0b1729;
                            border: 1px solid #1d3555;
                            border-radius: 18px;
                            padding: 36px;
                            max-width: 520px;
                            text-align: center;
                            box-shadow: 0 20px 60px rgba(0,0,0,.35);
                        }}
                        h1 {{ color: #2f81f7; }}
                        p {{ line-height: 1.6; color: #c8d4e6; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Google Drive bağlandı ✅</h1>
                        <p><b>{drive_email}</b> hesabı ConnectDesk'e bağlandı.</p>
                        <p>Bu sekmeyi kapatıp ConnectDesk uygulamasına dönebilirsin.</p>
                    </div>
                </body>
            </html>
            """
        )
    except Exception as e:
        return HTMLResponse(
            f"""
            <html>
                <head><title>ConnectDesk Google Drive Hata</title><meta charset="utf-8"></head>
                <body style="font-family:Arial;background:#160b0b;color:#fff;padding:40px;">
                    <h1>Google Drive bağlanamadı ❌</h1>
                    <p>{str(e)}</p>
                    <p>ConnectDesk'e dönüp tekrar deneyebilirsin.</p>
                </body>
            </html>
            """,
            status_code=500
        )


@app.get("/users/{user_id}/contacts")
def get_contacts(user_id: str):
    user = require_user(user_id)

    contacts = list_contacts(user["id"])

    return {
        "success": True,
        "user": user,
        "contacts": contacts
    }


@app.post("/contacts")
def add_contact(
    user_id: str = Form(...),
    name: str = Form(...),
    phone: str = Form(""),
    note: str = Form(""),
    email: str = Form(""),
    company: str = Form(""),
    drive: str = Form("")
):
    user = require_user(user_id)

    name = str(name).strip()
    phone = str(phone).strip()
    note = str(note).strip()

    contact = create_contact(
        user_id=user["id"],
        name=name,
        phone=phone,
        note=note,
        google_folder_id="",
        email=email,
        company=company,
        drive=drive
    )

    return {
        "success": True,
        "contact": contact
    }


@app.put("/contacts/{contact_id}")
def update_contact(
    contact_id: str,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    company: str = Form(""),
    drive: str = Form("")
):
    old_contact = require_contact(contact_id)

    name = str(name or "").strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Ad soyad bos olamaz."
        )

    updated_contact = update_contact_details(
        contact_id=str(contact_id).strip(),
        name=name,
        phone=phone,
        email=email,
        company=company,
        drive=drive
    )

    if not updated_contact:
        raise HTTPException(
            status_code=404,
            detail="Kisi bulunamadi."
        )

    user_id = str(updated_contact.get("user_id", "") or old_contact.get("user_id", "")).strip()
    folder_id = str(updated_contact.get("google_folder_id", "") or old_contact.get("google_folder_id", "")).strip()

    drive_folder_renamed = False
    backup_folder_renamed = False

    if user_id and folder_id:
        new_folder_name = f"{safe_drive_name(name)}_{updated_contact['id']}"

        try:
            rename_drive_file(user_id, folder_id, new_folder_name)
            updated_contact["drive"] = new_folder_name
            drive_folder_renamed = True
        except Exception as exc:
            updated_contact["drive_rename_error"] = str(exc)

    try:
        backup_rename_result = rename_contact_recovery_folder_if_exists(
            target_user_id=user_id,
            contact_id=updated_contact["id"],
            new_contact_name=name
        )
        backup_folder_renamed = bool(backup_rename_result.get("renamed"))
    except Exception as exc:
        updated_contact["backup_drive_rename_error"] = str(exc)

    return {
        "success": True,
        "contact": updated_contact,
        "drive_folder_renamed": drive_folder_renamed,
        "backup_folder_renamed": backup_folder_renamed
    }


@app.put("/contacts/{contact_id}/note")
def update_note(
    contact_id: str,
    note: str = Form("")
):
    contact = update_contact_note(
        contact_id=str(contact_id).strip(),
        note=note
    )

    if not contact:
        raise HTTPException(
            status_code=404,
            detail="Kisi bulunamadi."
        )

    return {
        "success": True,
        "contact": contact
    }


@app.post("/contacts/{contact_id}/profile-image")
async def upload_contact_profile_image(
    contact_id: str,
    file: UploadFile = File(...)
):
    contact = require_contact(contact_id)

    content_type = str(file.content_type or "").lower()

    if content_type and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Sadece resim dosyasi yukleyebilirsiniz."
        )

    folder_id = get_or_create_folder_for_contact(contact)

    user_id = str(contact.get("user_id", "")).strip()

    old_profile_file_id = str(contact.get("profile_image_file_id", "")).strip()

    if old_profile_file_id:
        try:
            delete_drive_file(user_id, old_profile_file_id)
        except Exception:
            pass

    original_filename = file.filename or "profil_resmi"
    temp_filename = f"__profile__{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded_file = upload_file_to_folder(
            user_id=user_id,
            file_path=temp_path,
            folder_id=folder_id
        )

        updated_contact = update_contact_profile_image(
            contact_id=contact["id"],
            file_info=uploaded_file
        )

        return {
            "success": True,
            "contact": updated_contact,
            "profile_image": uploaded_file
        }

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except PermissionError:
            pass


@app.delete("/contacts/{contact_id}")
def remove_contact(contact_id: str):
    contact = require_contact(contact_id)

    delete_contact(contact["id"])

    return {
        "success": True,
        "message": "Kisi veritabanindan silindi. Drive klasoru korunuyor."
    }


@app.get("/contacts/{contact_id}/files")
def get_contact_files(contact_id: str):
    contact = require_contact(contact_id)

    folder_id = get_or_create_folder_for_contact(contact)

    files = list_files_in_folder(
        user_id=contact["user_id"],
        folder_id=folder_id
    )

    profile_file_id = str(contact.get("profile_image_file_id", "")).strip()
    profile_file_name = str(contact.get("profile_image_name", "")).strip()

    visible_files = []

    for item in files:
        item_id = str(item.get("id", "")).strip()
        item_name = str(item.get("name", "")).strip()

        if profile_file_id and item_id == profile_file_id:
            continue

        if profile_file_name and item_name == profile_file_name:
            continue

        if item_name.startswith("__profile__"):
            continue

        visible_files.append(item)

    return {
        "success": True,
        "contact": contact,
        "files": visible_files
    }


@app.post("/contacts/{contact_id}/files/upload")
async def upload_contact_file(
    contact_id: str,
    file: UploadFile = File(...),
    backup_password: str = Form("")
):
    contact = require_contact(contact_id)

    user = require_user(contact["user_id"])
    folder_id = get_or_create_folder_for_contact(contact)

    original_filename = file.filename or "dosya"
    temp_filename = f"{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    backup_settings = get_user_backup_settings(user["id"])
    backup_enabled = bool(backup_settings.get("backup_enabled"))

    backup_password = str(backup_password or "").strip()

    if backup_enabled:
        if not backup_password:
            raise HTTPException(
                status_code=400,
                detail="Yedekleme acik. Dosya yuklemek icin yedekleme sifresi gerekli."
            )

        if not verify_backup_password(backup_password, backup_settings.get("backup_password_hash", "")):
            raise HTTPException(
                status_code=400,
                detail="Yedekleme sifresi hatali."
            )

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded_file = upload_file_to_folder(
            user_id=contact["user_id"],
            file_path=temp_path,
            folder_id=folder_id
        )

        file_record = save_file_record(
            contact_id=contact["id"],
            google_file_id=uploaded_file.get("id", ""),
            file_name=uploaded_file.get("name", ""),
            mime_type=uploaded_file.get("mimeType", ""),
            web_view_link=uploaded_file.get("webViewLink", ""),
            web_content_link=uploaded_file.get("webContentLink", "")
        )

        recovery_backup_file = None

        if backup_enabled:
            recovery_backup_file = backup_uploaded_file_for_contact(
                user=user,
                contact=contact,
                local_file_path=temp_path,
                original_filename=original_filename,
                backup_password=backup_password
            )

            save_file_record_recovery_backup(
                file_record_id=file_record["id"],
                recovery_backup_file_id=recovery_backup_file.get("id", ""),
                recovery_backup_file_name=recovery_backup_file.get("name", ""),
                recovery_backup_web_view_link=recovery_backup_file.get("webViewLink", ""),
                recovery_backup_web_content_link=recovery_backup_file.get("webContentLink", "")
            )

        return {
            "success": True,
            "contact": contact,
            "folder_id": folder_id,
            "file": uploaded_file,
            "file_record": file_record,
            "recovery_backup_enabled": backup_enabled,
            "recovery_backup_file": recovery_backup_file
        }

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except PermissionError:
            pass


@app.delete("/files/{google_file_id}")
def delete_file(google_file_id: str):
    google_file_id = str(google_file_id).strip()

    file_record = get_file_record_by_any_google_id(google_file_id)

    if not file_record:
        raise HTTPException(
            status_code=404,
            detail="Dosya kaydi bulunamadi."
        )

    contact = require_contact(file_record.get("contact_id", ""))

    original_id = str(file_record.get("google_file_id", "") or "").strip()

    if original_id:
        try:
            delete_drive_file(contact["user_id"], original_id)
        except Exception:
            pass

    delete_file_record_by_google_id(original_id or google_file_id)

    return {
        "success": True,
        "message": "Dosya kullanicinin Google Drive hesabindan silindi."
    }


@app.put("/files/{google_file_id}/replace")
async def replace_file(
    google_file_id: str,
    file: UploadFile = File(...)
):
    google_file_id = str(google_file_id).strip()

    file_record = get_file_record_by_google_id(google_file_id)

    if not file_record:
        raise HTTPException(
            status_code=404,
            detail="Dosya kaydi bulunamadi."
        )

    contact = require_contact(file_record.get("contact_id", ""))

    original_filename = file.filename or "dosya"
    temp_filename = f"{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        updated_file = replace_file_content(
            user_id=contact["user_id"],
            file_id=google_file_id,
            file_path=temp_path
        )

        backup_file_id = str(file_record.get("backup_google_file_id", "") or "").strip()
        backup_updated_file = None

        if backup_file_id:
            try:
                backup_updated_file = replace_file_content(
                    user_id=contact["user_id"],
                    file_id=backup_file_id,
                    file_path=temp_path
                )
            except Exception:
                backup_updated_file = None

        return {
            "success": True,
            "file": updated_file,
            "backup_file": backup_updated_file
        }

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except PermissionError:
            pass


@app.post("/users/{user_id}/backup/enable")
def enable_backup(
    user_id: str,
    backup_password: str = Form(...)
):
    user = require_user(user_id)

    backup_password = str(backup_password or "").strip()

    if len(backup_password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Yedekleme sifresi en az 4 karakter olmali."
        )

    updated_user = set_backup_enabled(
        user_id=user["id"],
        enabled=True,
        backup_password_hash=hash_backup_password(backup_password)
    )

    if not updated_user:
        raise HTTPException(status_code=404, detail="Kullanici bulunamadi.")

    return {
        "success": True,
        "backup_enabled": True,
        "message": "Yedekleme acildi."
    }


@app.post("/users/{user_id}/backup/disable")
def disable_backup(user_id: str):
    user = require_user(user_id)

    updated_user = set_backup_enabled(
        user_id=user["id"],
        enabled=False
    )

    if not updated_user:
        raise HTTPException(status_code=404, detail="Kullanici bulunamadi.")

    return {
        "success": True,
        "backup_enabled": False,
        "message": "Yedekleme kapatildi."
    }


@app.get("/users/{user_id}/backup/status")
def user_backup_status(user_id: str):
    user = require_user(user_id)
    status = get_backup_status(user["id"])

    return {
        "success": True,
        "user_id": user["id"],
        **status
    }


@app.post("/users/{user_id}/backup/recovery/create")
def create_recovery_backup(
    user_id: str,
    backup_password: str = Form(...)
):
    user = require_user(user_id)

    backup_password = str(backup_password or "").strip()

    if len(backup_password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Yedekleme sifresi en az 4 karakter olmali."
        )

    backup_settings = get_user_backup_settings(user["id"])

    if not backup_settings.get("backup_enabled"):
        raise HTTPException(
            status_code=400,
            detail="Yedekleme kapali. Once yedeklemeyi acin."
        )

    if not verify_backup_password(backup_password, backup_settings.get("backup_password_hash", "")):
        raise HTTPException(
            status_code=400,
            detail="Yedekleme sifresi hatali."
        )

    contacts = list_contacts(user["id"])
    files = list_user_file_records(user["id"])

    uploaded = upload_encrypted_recovery_backup(
        user=user,
        contacts=contacts,
        files=files,
        backup_password=backup_password
    )

    save_recovery_backup_record(
        user_id=user["id"],
        recovery_file_id=uploaded.get("id", ""),
        recovery_file_name=uploaded.get("name", "")
    )

    return {
        "success": True,
        "message": "Sifreli kurtarma yedegi olusturuldu.",
        "file": uploaded
    }


@app.post("/users/{user_id}/backup/recovery/unlock")
def unlock_recovery_backup(
    user_id: str,
    backup_password: str = Form(...)
):
    user = require_user(user_id)

    backup_password = str(backup_password or "").strip()

    if len(backup_password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Yedekleme sifresi en az 4 karakter olmali."
        )

    backup_settings = get_user_backup_settings(user["id"])

    if not backup_settings.get("backup_enabled"):
        raise HTTPException(
            status_code=400,
            detail="Yedekleme kapali. Once yedeklemeyi acin."
        )

    if not verify_backup_password(backup_password, backup_settings.get("backup_password_hash", "")):
        raise HTTPException(
            status_code=400,
            detail="Yedekleme sifresi hatali."
        )

    latest_file = get_latest_recovery_file(user["id"])

    if not latest_file:
        raise HTTPException(
            status_code=404,
            detail="Kurtarma yedegi bulunamadi. Once yedek olusturun."
        )

    try:
        encrypted_text = download_recovery_file_text(latest_file.get("id", ""))
        recovered_data = decrypt_recovery_backup_text(encrypted_text, backup_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yedek acilamadi: {str(e)}")

    return {
        "success": True,
        "message": "Kurtarma yedegi acildi.",
        "file": latest_file,
        "data": recovered_data
    }


@app.post("/users/{user_id}/backup/change-password")
def change_backup_password(
    user_id: str,
    old_backup_password: str = Form(...),
    new_backup_password: str = Form(...),
    new_backup_password_repeat: str = Form("")
):
    user = require_user(user_id)

    old_backup_password = str(old_backup_password or "").strip()
    new_backup_password = str(new_backup_password or "").strip()
    new_backup_password_repeat = str(new_backup_password_repeat or "").strip()

    if len(old_backup_password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Eski yedekleme sifresi en az 4 karakter olmali."
        )

    if len(new_backup_password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Yeni yedekleme sifresi en az 4 karakter olmali."
        )

    if new_backup_password_repeat and new_backup_password != new_backup_password_repeat:
        raise HTTPException(
            status_code=400,
            detail="Yeni yedekleme sifreleri ayni degil."
        )

    if old_backup_password == new_backup_password:
        raise HTTPException(
            status_code=400,
            detail="Yeni yedekleme sifresi eski sifreyle ayni olamaz."
        )

    backup_settings = get_user_backup_settings(user["id"])

    if not backup_settings.get("backup_enabled"):
        raise HTTPException(
            status_code=400,
            detail="Yedekleme kapali. Once yedeklemeyi acin."
        )

    if not verify_backup_password(old_backup_password, backup_settings.get("backup_password_hash", "")):
        raise HTTPException(
            status_code=400,
            detail="Eski yedekleme sifresi hatali."
        )

    try:
        rotation_result = rotate_backup_password_for_all_files(
            user=user,
            old_backup_password=old_backup_password,
            new_backup_password=new_backup_password
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Yedek sifresi guncellenemedi: {str(exc)}"
        )

    updated_user = set_backup_enabled(
        user_id=user["id"],
        enabled=True,
        backup_password_hash=hash_backup_password(new_backup_password)
    )

    if not updated_user:
        raise HTTPException(status_code=404, detail="Kullanici bulunamadi.")

    return {
        "success": True,
        "message": "Yedek sifresi guncellendi.",
        "changed_file_count": int(rotation_result.get("changed", 0)),
        "checked_file_count": int(rotation_result.get("checked", 0)),
        "files": rotation_result.get("files", [])
    }


def recovery_escape(value):
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
    )


def recovery_layout(title: str, body: str) -> str:
    safe_title = recovery_escape(title)
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#050b14;color:#f8fafc;font-family:Segoe UI,Arial,sans-serif;min-height:100vh}}
.wrap{{max-width:1180px;margin:0 auto;padding:26px 16px 50px}}
.top{{display:flex;align-items:center;gap:14px;margin-bottom:20px}}
.logo{{width:52px;height:52px;border-radius:16px;background:#111827;display:grid;place-items:center;font-size:28px;font-weight:800}}
h1{{margin:0;font-size:clamp(26px,4vw,38px)}} h2{{margin-top:0}}
p{{color:#b6c2d2;line-height:1.55}}
.card{{background:#0b1729;border:1px solid #1e426d;border-radius:20px;padding:22px;margin-bottom:18px}}
label{{display:block;color:#b6c2d2;font-weight:700;margin:14px 0 7px}}
input{{width:100%;height:46px;border-radius:12px;border:1px solid #1e426d;background:#07111f;color:#f8fafc;padding:0 14px;font-size:15px}}
button,.btn{{display:inline-flex;align-items:center;justify-content:center;height:44px;border:0;border-radius:12px;background:#2775ea;color:#fff;padding:0 18px;font-weight:800;text-decoration:none;cursor:pointer;margin-top:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}}
.item{{background:#10243d;border:1px solid #1e426d;border-radius:16px;padding:16px;overflow-wrap:anywhere}}
.item h3{{margin:0 0 8px;font-size:18px}}
.meta{{color:#b6c2d2;font-size:13px;margin:5px 0}}
.warn{{border-color:#7f1d1d;background:#351014}}
a{{color:#93c5fd}}
@media(max-width:720px){{.wrap{{padding:18px 12px 42px}}.card{{padding:16px;border-radius:16px}}}}
</style>
</head>
<body>
<main class="wrap">
<div class="top"><div class="logo">C</div><div><h1>{safe_title}</h1><p>ConnectDesk şifreli kurtarma paneli</p></div></div>
{body}
</main>
</body>
</html>"""


@app.get("/recovery", response_class=HTMLResponse)
def recovery_page_safe():
    try:
        body = """
<section class="card">
<h2>Yedeğe eriş</h2>
<p>Google Drive içindeki <b>.enc</b> dosyaları doğrudan açılmaz. Bu panel e-posta ve yedek şifresiyle en son kurtarma yedeğini çözer.</p>
<form method="post" action="/recovery/open">
<label>Kullanıcı e-posta adresi</label>
<input name="email" type="email" placeholder="ornek@mail.com" required>
<label>Yedekleme şifresi</label>
<input name="backup_password" type="password" placeholder="Yedekleme şifren" required>
<button type="submit">Yedeği Aç</button>
</form>
</section>
<section class="card"><h3>Not</h3><p>Drive klasöründe .enc görünmesi normal. İçeriği bu panel açar.</p></section>
"""
        return HTMLResponse(content=recovery_layout("ConnectDesk Kurtarma", body), status_code=200)
    except Exception as exc:
        return HTMLResponse(content=f"<pre>Recovery page error: {recovery_escape(exc)}</pre>", status_code=500)


@app.post("/recovery/open", response_class=HTMLResponse)
def recovery_open_safe(
    email: str = Form(...),
    backup_password: str = Form(...)
):
    email = str(email or "").strip().lower()
    backup_password = str(backup_password or "").strip()

    try:
        user = get_user(email)

        if not user:
            raise ValueError("Bu e-posta ile kayıtlı kullanıcı bulunamadı.")

        latest_file = get_latest_recovery_file(str(user.get("id", "")))

        if not latest_file:
            raise ValueError("Bu kullanıcı için kurtarma yedeği bulunamadı.")

        encrypted_text = download_recovery_file_text(str(latest_file.get("id", "")))
        data = decrypt_recovery_backup_text(encrypted_text, backup_password)

        contacts = data.get("contacts", []) or []
        files = data.get("files", []) or []

        files_by_contact = {}
        for file_item in files:
            if not isinstance(file_item, dict):
                continue
            contact_id = str(file_item.get("contact_id") or file_item.get("person_id") or file_item.get("contactId") or "")
            files_by_contact.setdefault(contact_id, []).append(file_item)

        cards = []

        for contact in contacts:
            if not isinstance(contact, dict):
                continue

            cid = str(contact.get("id", "") or "")
            name = recovery_escape(contact.get("name", "İsimsiz kişi"))
            phone = recovery_escape(contact.get("phone", ""))
            mail = recovery_escape(contact.get("email", ""))
            company = recovery_escape(contact.get("company", ""))
            note = recovery_escape(contact.get("note", ""))

            rows = []
            for f in files_by_contact.get(cid, []):
                fname = recovery_escape(f.get("name") or f.get("filename") or f.get("original_filename") or f.get("drive_file_name") or "Dosya")
                link = str(f.get("webViewLink") or f.get("web_content_link") or f.get("webContentLink") or f.get("url") or "")
                if link:
                    rows.append(f'<div class="meta">📄 <a target="_blank" href="{recovery_escape(link)}">{fname}</a></div>')
                else:
                    rows.append(f'<div class="meta">📄 {fname}</div>')

            file_html = "".join(rows) if rows else '<div class="meta">Bu kişiye ait dosya kaydı yok.</div>'

            cards.append(f"""
<article class="item">
<h3>{name}</h3>
<div class="meta">Telefon: {phone or "-"}</div>
<div class="meta">E-posta: {mail or "-"}</div>
<div class="meta">Firma/Birim: {company or "-"}</div>
<div class="meta">Not: {note or "-"}</div>
<hr>{file_html}
</article>
""")

        if not cards:
            cards.append('<article class="item"><h3>Kişi yok</h3><p>Bu yedekte kayıtlı kişi bulunamadı.</p></article>')

        body = f"""
<section class="card">
<h2>Yedek açıldı</h2>
<p>Kullanıcı: <b>{recovery_escape(email)}</b><br>Yedek dosyası: <b>{recovery_escape(latest_file.get("name", ""))}</b><br>Kişi sayısı: <b>{len(contacts)}</b> · Dosya kaydı sayısı: <b>{len(files)}</b></p>
<a class="btn" href="/recovery">Başka yedek aç</a>
</section>
<section class="grid">{''.join(cards)}</section>
"""
        return HTMLResponse(content=recovery_layout("Kurtarma Yedeği", body), status_code=200)

    except Exception as exc:
        body = f"""
<section class="card warn">
<h2>Yedek açılamadı</h2>
<p>{recovery_escape(str(exc))}</p>
<a class="btn" href="/recovery">Tekrar dene</a>
</section>
"""
        return HTMLResponse(content=recovery_layout("Yedek Açılamadı", body), status_code=400)


@app.post("/forgot-password/request-code")
def forgot_password_request_code(
    email: str = Form(...)
):
    email = str(email or "").strip().lower()
    user = get_user(email)

    if not user:
        raise HTTPException(status_code=404, detail="Bu e-posta ile kullanici bulunamadi.")

    code = generate_reset_code()
    expires_at = int(time.time()) + 10 * 60

    save_password_reset_code(email=email, code=code, expires_at=expires_at)

    mail_sent = send_password_reset_code(email, code)

    response = {
        "success": True,
        "message": "Sifre yenileme kodu gonderildi.",
        "mail_sent": mail_sent
    }

    if not mail_sent:
        response["dev_code"] = code

    return response


@app.post("/forgot-password/verify-code")
def forgot_password_verify_code(
    email: str = Form(...),
    code: str = Form(...)
):
    email = str(email or "").strip().lower()
    code = str(code or "").strip()

    valid = verify_password_reset_code(
        email=email,
        code=code,
        now_ts=int(time.time())
    )

    if not valid:
        raise HTTPException(status_code=400, detail="Kod hatali veya suresi dolmus.")

    return {
        "success": True,
        "verified": True
    }


@app.post("/forgot-password/reset")
def forgot_password_reset(
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...)
):
    email = str(email or "").strip().lower()
    code = str(code or "").strip()
    new_password = str(new_password or "").strip()

    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Yeni sifre en az 4 karakter olmali.")

    valid = verify_password_reset_code(
        email=email,
        code=code,
        now_ts=int(time.time())
    )

    if not valid:
        raise HTTPException(status_code=400, detail="Kod hatali veya suresi dolmus.")

    updated = update_user_password_by_email(email, new_password)

    if not updated:
        raise HTTPException(status_code=404, detail="Kullanici bulunamadi.")

    mark_password_reset_code_used(email)

    return {
        "success": True,
        "message": "Sifre guncellendi."
    }


@app.get("/debug/contact/{contact_id}")
def debug_contact(contact_id: str):
    contact = get_contact(str(contact_id).strip())

    return {
        "success": True,
        "searched_contact_id": contact_id,
        "found": contact is not None,
        "contact": contact
    }
