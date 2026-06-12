import os
import shutil
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
    delete_file_record_by_google_id
)

from services.drive_service import (
    get_or_create_contact_folder,
    list_files_in_folder,
    upload_file_to_folder,
    delete_drive_file,
    replace_file_content
)


app = FastAPI(title="ConnectDesk API", version="1.0.0")

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


@app.get("/")
def home():
    return {
        "success": True,
        "message": "ConnectDesk API calisiyor"
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


@app.get("/users/{user_id}/contacts")
def get_contacts(user_id: str):
    user_id = str(user_id).strip()

    user = get_user(user_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Kullanici bulunamadi."
        )

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
    user_id = str(user_id).strip()
    name = str(name).strip()
    phone = str(phone).strip()
    note = str(note).strip()

    user = get_user(user_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Kullanici bulunamadi."
        )

    contact = create_contact(
        user_id=user["id"],
        name=name,
        phone=phone,
        note=note,
        google_folder_id=""
    )

    folder_id = get_or_create_contact_folder(
        contact_name=contact["name"],
        contact_id=contact["id"]
    )

    update_contact_folder_id(
        contact_id=contact["id"],
        google_folder_id=folder_id
    )

    contact["google_folder_id"] = folder_id

    return {
        "success": True,
        "contact": contact
    }


@app.put("/contacts/{contact_id}/note")
def update_note(
    contact_id: str,
    note: str = Form("")
):
    contact_id = str(contact_id).strip()

    contact = update_contact_note(
        contact_id=contact_id,
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
    contact_id = str(contact_id).strip()

    contact = get_contact(contact_id)

    if not contact:
        raise HTTPException(
            status_code=404,
            detail="Kisi bulunamadi."
        )

    content_type = str(file.content_type or "").lower()

    if content_type and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Sadece resim dosyasi yukleyebilirsiniz."
        )

    folder_id = str(contact.get("google_folder_id", "")).strip()

    if not folder_id:
        folder_id = get_or_create_contact_folder(
            contact_name=contact.get("name", "Kisi"),
            contact_id=contact["id"]
        )

        update_contact_folder_id(
            contact_id=contact["id"],
            google_folder_id=folder_id
        )

    old_profile_file_id = str(contact.get("profile_image_file_id", "")).strip()

    if old_profile_file_id:
        try:
            delete_drive_file(old_profile_file_id)
        except Exception:
            pass

    original_filename = file.filename or "profil_resmi"
    temp_filename = f"__profile__{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded_file = upload_file_to_folder(
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
    contact_id = str(contact_id).strip()

    contact = get_contact(contact_id)

    if not contact:
        raise HTTPException(
            status_code=404,
            detail="Kisi bulunamadi."
        )

    delete_contact(contact_id)

    return {
        "success": True,
        "message": "Kisi veritabanindan silindi. Drive klasoru korunuyor."
    }


@app.get("/contacts/{contact_id}/files")
def get_contact_files(contact_id: str):
    contact_id = str(contact_id).strip()

    contact = get_contact(contact_id)

    if not contact:
        raise HTTPException(
            status_code=404,
            detail="Kisi bulunamadi."
        )

    folder_id = str(contact.get("google_folder_id", "")).strip()

    if not folder_id:
        folder_id = get_or_create_contact_folder(
            contact_name=contact.get("name", "Kisi"),
            contact_id=contact["id"]
        )

        update_contact_folder_id(
            contact_id=contact["id"],
            google_folder_id=folder_id
        )

        contact["google_folder_id"] = folder_id

    files = list_files_in_folder(folder_id)

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
    contact_id = str(contact_id).strip()

    contact = get_contact(contact_id)

    if not contact:
        raise HTTPException(
            status_code=404,
            detail=f"Kisi bulunamadi. Gelen contact_id: {contact_id}"
        )

    folder_id = str(contact.get("google_folder_id", "")).strip()

    if not folder_id:
        folder_id = get_or_create_contact_folder(
            contact_name=contact.get("name", "Kisi"),
            contact_id=contact["id"]
        )

        update_contact_folder_id(
            contact_id=contact["id"],
            google_folder_id=folder_id
        )

    original_filename = file.filename or "dosya"
    temp_filename = f"{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded_file = upload_file_to_folder(
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

    delete_drive_file(google_file_id)
    delete_file_record_by_google_id(google_file_id)

    return {
        "success": True,
        "message": "Dosya Google Drive'dan silindi."
    }


@app.put("/files/{google_file_id}/replace")
async def replace_file(
    google_file_id: str,
    file: UploadFile = File(...)
):
    google_file_id = str(google_file_id).strip()

    original_filename = file.filename or "dosya"
    temp_filename = f"{uuid.uuid4()}_{original_filename}"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        updated_file = replace_file_content(
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
    contact_id = str(contact_id).strip()

    contact = get_contact(contact_id)

    return {
        "success": True,
        "searched_contact_id": contact_id,
        "found": contact is not None,
        "contact": contact
    }
