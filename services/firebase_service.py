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
    google_folder_id: str = ""
) -> Dict[str, Any]:
    db = init_firebase()

    ref = db.collection("contacts").document()

    data = {
        "user_id": str(user_id).strip(),
        "name": str(name).strip(),
        "phone": str(phone).strip(),
        "note": str(note).strip(),
        "google_folder_id": str(google_folder_id).strip(),
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
