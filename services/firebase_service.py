import os
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List

import firebase_admin
from firebase_admin import credentials, firestore


_db = None


def init_firebase():
    global _db

    if _db is not None:
        return _db

    json_text = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
    key_path = os.getenv("FIREBASE_KEY_PATH", "firebase_key.json")

    if not firebase_admin._apps:
        if json_text:
            cred_dict = json.loads(json_text)
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.Certificate(key_path)

        firebase_admin.initialize_app(cred)

    _db = firestore.client()
    return _db


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    email = str(email).strip().lower()

    existing = db.collection("users").where("email", "==", email).limit(1).stream()

    for _ in existing:
        return None

    ref = db.collection("users").document()

    data = {
        "email": email,
        "password_hash": hash_password(password),
        "created_at": now_iso()
    }

    ref.set(data)

    return {
        "id": ref.id,
        "email": email
    }


def login_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    email = str(email).strip().lower()
    password_hash = hash_password(password)

    docs = db.collection("users").where("email", "==", email).limit(1).stream()

    for doc in docs:
        data = doc.to_dict()

        if data.get("password_hash") == password_hash:
            return {
                "id": doc.id,
                "email": data.get("email")
            }

    return None


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    user_id = str(user_id).strip()

    doc = db.collection("users").document(user_id).get()

    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    email = user_id.lower()

    docs = db.collection("users").where("email", "==", email).limit(1).stream()

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    return None


def create_contact(
    user_id: str,
    name: str,
    phone: str = "",
    note: str = "",
    google_folder_id: str = "",
    email: str = "",
    company: str = "",
    drive: str = ""
) -> Dict[str, Any]:
    db = init_firebase()

    ref = db.collection("contacts").document()

    data = {
        "user_id": str(user_id).strip(),
        "name": str(name).strip(),
        "phone": str(phone).strip(),
        "note": str(note).strip(),
        "google_folder_id": str(google_folder_id).strip(),
        "email": str(email).strip(),
        "company": str(company).strip(),
        "drive": str(drive).strip(),
        "created_at": now_iso(),
        "updated_at": now_iso()
    }

    ref.set(data)

    data["id"] = ref.id

    return data


def update_contact_folder_id(contact_id: str, google_folder_id: str) -> None:
    db = init_firebase()

    db.collection("contacts").document(str(contact_id).strip()).update({
        "google_folder_id": str(google_folder_id).strip(),
        "updated_at": now_iso()
    })



def update_contact_details(
    contact_id: str,
    name: str,
    phone: str = "",
    email: str = "",
    company: str = "",
    drive: str = ""
) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    contact_id = str(contact_id).strip()
    name = str(name or "").strip()

    if not name:
        raise ValueError("Ad soyad bos olamaz.")

    ref = db.collection("contacts").document(contact_id)
    doc = ref.get()

    if not doc.exists:
        return None

    update_data = {
        "name": name,
        "phone": str(phone or "").strip(),
        "email": str(email or "").strip(),
        "company": str(company or "").strip(),
        "drive": str(drive or "").strip(),
        "updated_at": now_iso()
    }

    ref.update(update_data)

    updated_doc = ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id

    return data

def update_contact_note(contact_id: str, note: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    contact_id = str(contact_id).strip()
    note = str(note).strip()

    ref = db.collection("contacts").document(contact_id)
    doc = ref.get()

    if not doc.exists:
        return None

    ref.update({
        "note": note,
        "updated_at": now_iso()
    })

    updated_doc = ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id

    return data


def update_contact_profile_image(contact_id: str, file_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    contact_id = str(contact_id).strip()

    ref = db.collection("contacts").document(contact_id)
    doc = ref.get()

    if not doc.exists:
        return None

    ref.update({
        "profile_image_file_id": str(file_info.get("id", "")).strip(),
        "profile_image_name": str(file_info.get("name", "")).strip(),
        "profile_image_mime_type": str(file_info.get("mimeType", "")).strip(),
        "profile_image_web_view_link": str(file_info.get("webViewLink", "")).strip(),
        "profile_image_web_content_link": str(file_info.get("webContentLink", "")).strip(),
        "profile_image_view_url": str(file_info.get("view_url", "")).strip(),
        "profile_image_download_url": str(file_info.get("download_url", "")).strip(),
        "updated_at": now_iso()
    })

    updated_doc = ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id

    return data


def list_contacts(user_id: str) -> List[Dict[str, Any]]:
    db = init_firebase()

    user_id = str(user_id).strip()

    docs = db.collection("contacts").where("user_id", "==", user_id).stream()

    contacts = []

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        contacts.append(data)

    contacts.sort(key=lambda x: x.get("name", "").lower())

    return contacts


def get_contact(contact_id: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    contact_id = str(contact_id).strip()

    doc = db.collection("contacts").document(contact_id).get()

    if not doc.exists:
        return None

    data = doc.to_dict()
    data["id"] = doc.id

    return data


def delete_contact(contact_id: str) -> None:
    db = init_firebase()

    db.collection("contacts").document(str(contact_id).strip()).delete()


def save_file_record(
    contact_id: str,
    google_file_id: str,
    file_name: str,
    mime_type: str = "",
    web_view_link: str = "",
    web_content_link: str = ""
) -> Dict[str, Any]:
    db = init_firebase()

    ref = db.collection("contact_files").document()

    data = {
        "contact_id": str(contact_id).strip(),
        "google_file_id": str(google_file_id).strip(),
        "file_name": str(file_name).strip(),
        "mime_type": str(mime_type).strip(),
        "web_view_link": str(web_view_link).strip(),
        "web_content_link": str(web_content_link).strip(),
        "created_at": now_iso()
    }

    ref.set(data)

    data["id"] = ref.id

    return data


def delete_file_record_by_google_id(google_file_id: str) -> None:
    db = init_firebase()

    google_file_id = str(google_file_id).strip()

    docs = db.collection("contact_files").where("google_file_id", "==", google_file_id).stream()

    for doc in docs:
        doc.reference.delete()


def save_user_drive_token(
    user_id: str,
    token_json: Dict[str, Any],
    drive_email: str = "",
    drive_display_name: str = ""
) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    user_id = str(user_id).strip()

    if not user_id:
        return None

    ref = db.collection("users").document(user_id)
    doc = ref.get()

    if not doc.exists:
        return None

    update_data = {
        "drive_token_json": token_json,
        "drive_connected": True,
        "drive_updated_at": now_iso()
    }

    if drive_email:
        update_data["drive_email"] = str(drive_email).strip()

    if drive_display_name:
        update_data["drive_display_name"] = str(drive_display_name).strip()

    ref.update(update_data)

    updated_doc = ref.get()
    data = updated_doc.to_dict()
    data["id"] = updated_doc.id

    return data


def get_user_drive_token(user_id: str) -> Optional[Dict[str, Any]]:
    user = get_user(user_id)

    if not user:
        return None

    token_json = user.get("drive_token_json")

    if isinstance(token_json, dict):
        return token_json

    if isinstance(token_json, str) and token_json.strip():
        try:
            return json.loads(token_json)
        except Exception:
            return None

    return None


def get_user_drive_status(user_id: str) -> Dict[str, Any]:
    user = get_user(user_id)

    if not user:
        return {
            "connected": False,
            "drive_email": "",
            "drive_display_name": ""
        }

    token_json = user.get("drive_token_json")

    connected = bool(token_json)

    return {
        "connected": connected,
        "drive_email": str(user.get("drive_email", "") or ""),
        "drive_display_name": str(user.get("drive_display_name", "") or ""),
        "drive_updated_at": str(user.get("drive_updated_at", "") or "")
    }


def get_file_record_by_google_id(google_file_id: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    google_file_id = str(google_file_id).strip()

    docs = db.collection("contact_files").where("google_file_id", "==", google_file_id).limit(1).stream()

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    return None



# ============================================================
# CONNECTDESK BACKUP + PASSWORD RESET HELPERS
# ============================================================

def set_backup_enabled(user_id: str, enabled: bool, backup_password_hash: str = "") -> Optional[Dict[str, Any]]:
    db = init_firebase()

    user_id = str(user_id).strip()
    ref = db.collection("users").document(user_id)
    doc = ref.get()

    if not doc.exists:
        return None

    update_data = {
        "backup_enabled": bool(enabled),
        "backup_updated_at": now_iso()
    }

    if backup_password_hash:
        update_data["backup_password_hash"] = str(backup_password_hash).strip()

    ref.update(update_data)

    updated = ref.get().to_dict()
    updated["id"] = user_id
    return updated


def get_backup_status(user_id: str) -> Dict[str, Any]:
    user = get_user(user_id)

    if not user:
        return {
            "backup_enabled": False,
            "last_backup_at": "",
            "recovery_file_id": ""
        }

    return {
        "backup_enabled": bool(user.get("backup_enabled")),
        "last_backup_at": str(user.get("last_backup_at", "") or ""),
        "recovery_file_id": str(user.get("recovery_file_id", "") or "")
    }


def save_recovery_backup_record(user_id: str, recovery_file_id: str, recovery_file_name: str = "") -> None:
    db = init_firebase()

    db.collection("users").document(str(user_id).strip()).update({
        "recovery_file_id": str(recovery_file_id).strip(),
        "recovery_file_name": str(recovery_file_name).strip(),
        "last_backup_at": now_iso(),
        "updated_at": now_iso()
    })


def save_file_record_with_backup(
    contact_id: str,
    google_file_id: str,
    backup_google_file_id: str = "",
    file_name: str = "",
    backup_file_name: str = "",
    mime_type: str = "",
    web_view_link: str = "",
    web_content_link: str = "",
    backup_web_view_link: str = "",
    backup_web_content_link: str = ""
) -> Dict[str, Any]:
    db = init_firebase()

    ref = db.collection("contact_files").document()

    data = {
        "contact_id": str(contact_id).strip(),
        "google_file_id": str(google_file_id).strip(),
        "backup_google_file_id": str(backup_google_file_id).strip(),
        "file_name": str(file_name).strip(),
        "backup_file_name": str(backup_file_name).strip(),
        "mime_type": str(mime_type).strip(),
        "web_view_link": str(web_view_link).strip(),
        "web_content_link": str(web_content_link).strip(),
        "backup_web_view_link": str(backup_web_view_link).strip(),
        "backup_web_content_link": str(backup_web_content_link).strip(),
        "created_at": now_iso()
    }

    ref.set(data)
    data["id"] = ref.id
    return data


def get_file_record_by_any_google_id(google_file_id: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()

    google_file_id = str(google_file_id).strip()

    for field_name in ["google_file_id", "backup_google_file_id"]:
        docs = db.collection("contact_files").where(field_name, "==", google_file_id).limit(1).stream()

        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data

    return None


def get_user_backup_settings(user_id: str) -> Dict[str, Any]:
    user = get_user(user_id)

    if not user:
        return {
            "backup_enabled": False,
            "backup_password_hash": "",
            "last_backup_at": "",
            "recovery_file_id": "",
            "recovery_file_name": ""
        }

    return {
        "backup_enabled": bool(user.get("backup_enabled")),
        "backup_password_hash": str(user.get("backup_password_hash", "") or ""),
        "last_backup_at": str(user.get("last_backup_at", "") or ""),
        "recovery_file_id": str(user.get("recovery_file_id", "") or ""),
        "recovery_file_name": str(user.get("recovery_file_name", "") or ""),
        "recovery_updated_at": str(user.get("backup_updated_at", "") or "")
    }


def save_file_record_recovery_backup(
    file_record_id: str,
    recovery_backup_file_id: str,
    recovery_backup_file_name: str = "",
    recovery_backup_web_view_link: str = "",
    recovery_backup_web_content_link: str = ""
) -> None:
    db = init_firebase()

    file_record_id = str(file_record_id).strip()

    if not file_record_id:
        return

    db.collection("contact_files").document(file_record_id).update({
        "recovery_backup_file_id": str(recovery_backup_file_id).strip(),
        "recovery_backup_file_name": str(recovery_backup_file_name).strip(),
        "recovery_backup_web_view_link": str(recovery_backup_web_view_link).strip(),
        "recovery_backup_web_content_link": str(recovery_backup_web_content_link).strip(),
        "recovery_backup_created_at": now_iso()
    })


def list_contact_files(contact_id: str) -> List[Dict[str, Any]]:
    db = init_firebase()

    contact_id = str(contact_id).strip()

    docs = db.collection("contact_files").where("contact_id", "==", contact_id).stream()

    files = []

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        files.append(data)

    files.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return files


def list_user_file_records(user_id: str) -> List[Dict[str, Any]]:
    contacts = list_contacts(user_id)

    all_files = []

    for contact in contacts:
        contact_id = str(contact.get("id", "")).strip()

        if not contact_id:
            continue

        for item in list_contact_files(contact_id):
            item["contact_name"] = contact.get("name", "")
            all_files.append(item)

    return all_files


def save_password_reset_code(email: str, code: str, expires_at: int) -> None:
    db = init_firebase()

    email = str(email).strip().lower()
    ref = db.collection("password_reset_codes").document(email)

    ref.set({
        "email": email,
        "code_hash": hash_password(str(code)),
        "expires_at": int(expires_at),
        "used": False,
        "created_at": now_iso()
    })


def verify_password_reset_code(email: str, code: str, now_ts: int) -> bool:
    db = init_firebase()

    email = str(email).strip().lower()
    doc = db.collection("password_reset_codes").document(email).get()

    if not doc.exists:
        return False

    data = doc.to_dict()

    if data.get("used"):
        return False

    if int(data.get("expires_at", 0)) < int(now_ts):
        return False

    return data.get("code_hash") == hash_password(str(code))


def mark_password_reset_code_used(email: str) -> None:
    db = init_firebase()

    email = str(email).strip().lower()
    db.collection("password_reset_codes").document(email).update({
        "used": True,
        "used_at": now_iso()
    })


def update_user_password_by_email(email: str, new_password: str) -> bool:
    db = init_firebase()

    email = str(email).strip().lower()
    docs = db.collection("users").where("email", "==", email).limit(1).stream()

    for doc in docs:
        doc.reference.update({
            "password_hash": hash_password(new_password),
            "updated_at": now_iso()
        })
        return True

    return False
