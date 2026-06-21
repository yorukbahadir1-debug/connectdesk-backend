import json
import os
import tempfile
import time
import uuid
from typing import Dict, Any, List

from services.crypto_service import encrypt_json, decrypt_json, encrypt_file_to_temp, verify_backup_password, reencrypt_payload_text
from services.backup_drive_service import (
    upload_user_recovery_file,
    upload_contact_recovery_file,
    list_user_encrypted_backup_files,
    download_backup_file_text,
    replace_backup_file_text
)


def backup_file_name(user: Dict[str, Any]) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"recovery_{ts}.enc"


def uploaded_file_backup_name(original_filename: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"file_{ts}_{uuid.uuid4().hex[:10]}.enc"


def create_encrypted_recovery_backup(
    user: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    files: List[Dict[str, Any]],
    backup_password: str
) -> Dict[str, Any]:
    backup_plain = {
        "type": "connectdesk_recovery_backup",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": {
            "id": user.get("id", ""),
            "email": user.get("email", "")
        },
        "contacts": contacts,
        "files": files
    }

    metadata = {
        "kind": "recovery",
        "created_at": backup_plain["created_at"]
    }

    return encrypt_json(backup_plain, backup_password, metadata=metadata)


def write_encrypted_payload_to_temp(payload: Dict[str, Any]) -> str:
    fd, temp_path = tempfile.mkstemp(prefix="connectdesk_recovery_", suffix=".enc")
    os.close(fd)

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return temp_path


def upload_encrypted_recovery_backup(
    user: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    files: List[Dict[str, Any]],
    backup_password: str
) -> Dict[str, Any]:
    payload = create_encrypted_recovery_backup(
        user=user,
        contacts=contacts,
        files=files,
        backup_password=backup_password
    )

    temp_path = write_encrypted_payload_to_temp(payload)
    file_name = backup_file_name(user)

    try:
        uploaded = upload_user_recovery_file(
            target_user_id=str(user.get("id", "")),
            file_path=temp_path,
            drive_file_name=file_name
        )
        return uploaded
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


def backup_uploaded_file_for_contact(
    user: Dict[str, Any],
    contact: Dict[str, Any],
    local_file_path: str,
    original_filename: str,
    backup_password: str
) -> Dict[str, Any]:
    metadata = {
        "kind": "contact_file",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    encrypted_path = encrypt_file_to_temp(
        file_path=local_file_path,
        password=backup_password,
        metadata=metadata
    )

    encrypted_name = uploaded_file_backup_name(original_filename)

    try:
        return upload_contact_recovery_file(
            target_user_id=str(user.get("id", "")),
            contact_id=str(contact.get("id", "")),
            contact_name=str(contact.get("name", "Kisi")),
            file_path=encrypted_path,
            drive_file_name=encrypted_name
        )
    finally:
        try:
            os.remove(encrypted_path)
        except Exception:
            pass


def require_valid_backup_password(backup_password: str, backup_password_hash: str) -> None:
    if not verify_backup_password(backup_password, backup_password_hash):
        raise ValueError("Yedekleme sifresi hatali.")



def decrypt_recovery_backup_text(encrypted_text: str, backup_password: str) -> Dict[str, Any]:
    try:
        payload = json.loads(str(encrypted_text or ""))
    except Exception as exc:
        raise ValueError("Yedek dosyasi JSON formatinda degil veya bozuk.") from exc

    data = decrypt_json(payload, backup_password)

    if not isinstance(data, dict):
        raise ValueError("Yedek dosyasi icerigi hatali.")

    return data



def rotate_backup_password_for_all_files(
    user: Dict[str, Any],
    old_backup_password: str,
    new_backup_password: str
) -> Dict[str, Any]:
    user_id = str(user.get("id", "") or "").strip()

    if not user_id:
        raise ValueError("Kullanici id bulunamadi.")

    files = list_user_encrypted_backup_files(user_id)

    if not files:
        return {
            "changed": 0,
            "checked": 0,
            "files": [],
            "message": "Degistirilecek sifreli yedek dosyasi bulunamadi."
        }

    prepared = []

    for item in files:
        file_id = str(item.get("id", "") or "").strip()
        file_name = str(item.get("name", "") or "").strip()

        if not file_id:
            continue

        encrypted_text = download_backup_file_text(file_id)
        new_encrypted_text = reencrypt_payload_text(
            encrypted_text=encrypted_text,
            old_password=old_backup_password,
            new_password=new_backup_password
        )

        prepared.append({
            "id": file_id,
            "name": file_name,
            "path": str(item.get("path", "") or file_name),
            "text": new_encrypted_text
        })

    changed_files = []

    for item in prepared:
        updated = replace_backup_file_text(
            file_id=item["id"],
            text_content=item["text"]
        )

        changed_files.append({
            "id": updated.get("id", item["id"]),
            "name": updated.get("name", item["name"]),
            "path": item.get("path", item["name"])
        })

    return {
        "changed": len(changed_files),
        "checked": len(files),
        "files": changed_files,
        "message": "Yedek sifresi tum sifreli yedek dosyalari icin guncellendi."
    }
