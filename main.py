import os
import shutil
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from services.firebase_service import (
    create_user,
    login_user,
    get_user,
    create_contact,
    update_contact_folder_id,
    update_contact_note,
    update_contact_profile_image,
    list_contacts,
    get_contact,
    delete_contact,
    save_file_record,
    delete_file_record_by_google_id,
    get_file_record_by_google_id,
    get_user_drive_status
)

from services.drive_service import (
    create_google_auth_url,
    finish_google_callback,
    get_or_create_contact_folder,
    list_files_in_folder,
    upload_file_to_folder,
    delete_drive_file,
    replace_file_content
)


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
    note: str = Form("")
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
        google_folder_id=""
    )

    return {
        "success": True,
        "contact": contact
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
    file: UploadFile = File(...)
):
    contact = require_contact(contact_id)

    folder_id = get_or_create_folder_for_contact(contact)

    original_filename = file.filename or "dosya"
    temp_filename = f"{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded_file = upload_file_to_folder(
            user_id=contact["user_id"],
            file_path=temp_path,
            folder_id=folder_id
        )

        save_file_record(
            contact_id=contact["id"],
            google_file_id=uploaded_file.get("id", ""),
            file_name=uploaded_file.get("name", ""),
            mime_type=uploaded_file.get("mimeType", ""),
            web_view_link=uploaded_file.get("webViewLink", ""),
            web_content_link=uploaded_file.get("webContentLink", "")
        )

        return {
            "success": True,
            "contact": contact,
            "folder_id": folder_id,
            "file": uploaded_file
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

    file_record = get_file_record_by_google_id(google_file_id)

    if not file_record:
        raise HTTPException(
            status_code=404,
            detail="Dosya kaydi bulunamadi."
        )

    contact = require_contact(file_record.get("contact_id", ""))

    delete_drive_file(contact["user_id"], google_file_id)
    delete_file_record_by_google_id(google_file_id)

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

        return {
            "success": True,
            "file": updated_file
        }

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except PermissionError:
            pass


@app.get("/debug/contact/{contact_id}")
def debug_contact(contact_id: str):
    contact = get_contact(str(contact_id).strip())

    return {
        "success": True,
        "searched_contact_id": contact_id,
        "found": contact is not None,
        "contact": contact
    }
