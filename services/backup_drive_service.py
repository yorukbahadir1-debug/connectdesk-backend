import os
import json
import tempfile
import time
from typing import Optional, Dict, Any, List

from googleapiclient.http import MediaFileUpload

from services.firebase_service import get_user
from services.drive_service import (
    find_folder_by_name,
    create_folder,
    upload_file_to_folder_as,
    delete_drive_file,
    init_drive,
    safe_drive_name,
    rename_drive_file
)


RECOVERY_BACKUP_ROOT_FOLDER_NAME = os.getenv(
    "RECOVERY_BACKUP_ROOT_FOLDER_NAME",
    os.getenv("BACKUP_ROOT_FOLDER_NAME", "ConnectDesk_Yedekler")
)

RECOVERY_BACKUP_USERS_FOLDER_NAME = os.getenv(
    "RECOVERY_BACKUP_USERS_FOLDER_NAME",
    "kullanicilar"
)

RECOVERY_BACKUP_RECOVERY_FOLDER_NAME = os.getenv(
    "RECOVERY_BACKUP_RECOVERY_FOLDER_NAME",
    "yedekler"
)

RECOVERY_BACKUP_CONTACTS_FOLDER_NAME = os.getenv(
    "RECOVERY_BACKUP_CONTACTS_FOLDER_NAME",
    "kisiler"
)

USER_INFO_FILE_NAME = "bilgi.json"


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def email_folder_name(email: str, fallback: str = "user") -> str:
    value = str(email or "").strip().lower()

    if not value:
        value = str(fallback or "user").strip().lower()

    value = value.replace("@", "_at_")
    value = value.replace(".", "_")
    value = safe_drive_name(value)

    return value or "user"


def get_recovery_owner_user() -> Dict[str, Any]:
    owner_user_id = os.getenv("RECOVERY_BACKUP_OWNER_USER_ID", "").strip()
    owner_email = os.getenv("RECOVERY_BACKUP_OWNER_EMAIL", "").strip().lower()

    owner = None

    if owner_user_id:
        owner = get_user(owner_user_id)

    if not owner and owner_email:
        owner = get_user(owner_email)

    if not owner:
        raise RuntimeError(
            "Recovery backup sahibi bulunamadi. .env icine RECOVERY_BACKUP_OWNER_EMAIL=yorukbahadir1@gmail.com ekleyin ve bu hesapla Drive baglantisi yapin."
        )

    return owner


def get_recovery_owner_user_id() -> str:
    owner = get_recovery_owner_user()
    return str(owner.get("id", "")).strip()


def get_or_create_recovery_root_folder() -> str:
    owner_user_id = get_recovery_owner_user_id()

    root_id = find_folder_by_name(owner_user_id, RECOVERY_BACKUP_ROOT_FOLDER_NAME)

    if root_id:
        return root_id

    return create_folder(owner_user_id, RECOVERY_BACKUP_ROOT_FOLDER_NAME)


def get_or_create_recovery_users_folder() -> str:
    owner_user_id = get_recovery_owner_user_id()
    root_id = get_or_create_recovery_root_folder()

    folder_id = find_folder_by_name(
        owner_user_id,
        RECOVERY_BACKUP_USERS_FOLDER_NAME,
        root_id
    )

    if folder_id:
        return folder_id

    return create_folder(
        owner_user_id,
        RECOVERY_BACKUP_USERS_FOLDER_NAME,
        root_id
    )


def get_target_user(target_user_id: str) -> Dict[str, Any]:
    user = get_user(str(target_user_id).strip())

    if not user:
        raise RuntimeError("Yedeklenecek kullanici bulunamadi.")

    return user


def get_target_user_folder_name(target_user_id: str) -> str:
    user = get_target_user(target_user_id)
    return email_folder_name(user.get("email", ""), fallback=user.get("id", target_user_id))


def get_or_create_user_recovery_folder(target_user_id: str) -> str:
    owner_user_id = get_recovery_owner_user_id()
    users_folder_id = get_or_create_recovery_users_folder()

    folder_name = get_target_user_folder_name(target_user_id)

    folder_id = find_folder_by_name(owner_user_id, folder_name, users_folder_id)

    if folder_id:
        return folder_id

    return create_folder(owner_user_id, folder_name, users_folder_id)


def find_file_by_name(folder_id: str, file_name: str) -> Optional[str]:
    owner_user_id = get_recovery_owner_user_id()
    service = init_drive(owner_user_id)

    safe_name = str(file_name or "").replace("'", "\\'")
    query = f"name='{safe_name}' and trashed=false and '{folder_id}' in parents"

    result = service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=1
    ).execute()

    files = result.get("files", []) or []

    if files:
        return files[0].get("id")

    return None


def upload_or_replace_text_file(folder_id: str, file_name: str, text_content: str) -> Dict[str, Any]:
    owner_user_id = get_recovery_owner_user_id()

    old_file_id = find_file_by_name(folder_id, file_name)

    if old_file_id:
        try:
            delete_drive_file(owner_user_id, old_file_id)
        except Exception:
            pass

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as f:
        f.write(str(text_content or ""))
        temp_path = f.name

    try:
        return upload_file_to_folder_as(
            user_id=owner_user_id,
            file_path=temp_path,
            folder_id=folder_id,
            drive_file_name=file_name
        )
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


def write_user_info_file(target_user_id: str) -> Dict[str, Any]:
    user = get_target_user(target_user_id)
    user_folder_id = get_or_create_user_recovery_folder(target_user_id)
    folder_name = get_target_user_folder_name(target_user_id)

    payload = {
        "type": "connectdesk_recovery_user_info",
        "email": str(user.get("email", "") or ""),
        "user_id": str(user.get("id", "") or ""),
        "folder_name": folder_name,
        "last_updated_at": now_text(),
        "note": "Bu dosya sadece yedegin kime ait oldugunu gosterir. Uygulama sifresi, yedekleme sifresi ve kisi/dosya icerikleri burada tutulmaz. Asil yedekler .enc dosyalarinda sifreli durur."
    }

    return upload_or_replace_text_file(
        folder_id=user_folder_id,
        file_name=USER_INFO_FILE_NAME,
        text_content=json.dumps(payload, ensure_ascii=False, indent=2)
    )


def get_or_create_user_recovery_subfolder(target_user_id: str, subfolder_name: str) -> str:
    owner_user_id = get_recovery_owner_user_id()
    user_folder_id = get_or_create_user_recovery_folder(target_user_id)

    folder_name = safe_drive_name(str(subfolder_name).strip())

    folder_id = find_folder_by_name(owner_user_id, folder_name, user_folder_id)

    if folder_id:
        return folder_id

    return create_folder(owner_user_id, folder_name, user_folder_id)


def get_or_create_contact_recovery_files_folder(target_user_id: str, contact_id: str, contact_name: str = "") -> str:
    owner_user_id = get_recovery_owner_user_id()
    contacts_root_id = get_or_create_user_recovery_subfolder(target_user_id, RECOVERY_BACKUP_CONTACTS_FOLDER_NAME)

    clean_contact_name = safe_drive_name(str(contact_name or "Kisi").strip())
    folder_name = f"{clean_contact_name}_{str(contact_id).strip()}"

    folder_id = find_folder_by_name(owner_user_id, folder_name, contacts_root_id)

    if folder_id:
        return folder_id

    return create_folder(owner_user_id, folder_name, contacts_root_id)



def rename_contact_recovery_folder_if_exists(target_user_id: str, contact_id: str, new_contact_name: str) -> Dict[str, Any]:
    owner_user_id = get_recovery_owner_user_id()
    contacts_root_id = get_or_create_user_recovery_subfolder(target_user_id, RECOVERY_BACKUP_CONTACTS_FOLDER_NAME)

    service = init_drive(owner_user_id)
    contact_id = str(contact_id or "").strip()
    suffix = "_" + contact_id
    new_folder_name = f"{safe_drive_name(str(new_contact_name or 'Kisi').strip())}_{contact_id}"

    result = service.files().list(
        q=f"'{contacts_root_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)",
        pageSize=100
    ).execute()

    for item in result.get("files", []) or []:
        current_name = str(item.get("name", "") or "")
        current_id = str(item.get("id", "") or "")

        if current_id and current_name.endswith(suffix):
            if current_name != new_folder_name:
                updated = rename_drive_file(owner_user_id, current_id, new_folder_name)
                return {
                    "renamed": True,
                    "old_name": current_name,
                    "new_name": new_folder_name,
                    "folder": updated
                }

            return {
                "renamed": False,
                "old_name": current_name,
                "new_name": new_folder_name,
                "folder": item
            }

    return {
        "renamed": False,
        "old_name": "",
        "new_name": new_folder_name,
        "folder": None
    }

def upload_recovery_file(file_path: str, folder_id: str, drive_file_name: str) -> Dict[str, Any]:
    owner_user_id = get_recovery_owner_user_id()

    return upload_file_to_folder_as(
        user_id=owner_user_id,
        file_path=file_path,
        folder_id=folder_id,
        drive_file_name=drive_file_name
    )


def upload_user_recovery_file(target_user_id: str, file_path: str, drive_file_name: str) -> Dict[str, Any]:
    write_user_info_file(target_user_id)
    folder_id = get_or_create_user_recovery_subfolder(target_user_id, RECOVERY_BACKUP_RECOVERY_FOLDER_NAME)
    return upload_recovery_file(file_path, folder_id, drive_file_name)


def upload_contact_recovery_file(target_user_id: str, contact_id: str, contact_name: str, file_path: str, drive_file_name: str) -> Dict[str, Any]:
    write_user_info_file(target_user_id)
    folder_id = get_or_create_contact_recovery_files_folder(target_user_id, contact_id, contact_name=contact_name)
    return upload_recovery_file(file_path, folder_id, drive_file_name)



def list_recovery_files(target_user_id: str):
    owner_user_id = get_recovery_owner_user_id()
    folder_id = get_or_create_user_recovery_subfolder(target_user_id, RECOVERY_BACKUP_RECOVERY_FOLDER_NAME)
    service = init_drive(owner_user_id)

    query = f"'{folder_id}' in parents and trashed=false and name contains 'recovery_'"

    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, webViewLink, webContentLink, createdTime, modifiedTime)",
        orderBy="createdTime desc",
        pageSize=20
    ).execute()

    return result.get("files", []) or []


def get_latest_recovery_file(target_user_id: str):
    files = list_recovery_files(target_user_id)

    if not files:
        return None

    return files[0]


def download_recovery_file_text(file_id: str) -> str:
    owner_user_id = get_recovery_owner_user_id()
    service = init_drive(owner_user_id)

    data = service.files().get_media(fileId=str(file_id).strip()).execute()

    if isinstance(data, bytes):
        return data.decode("utf-8")

    return str(data or "")



def list_child_items(folder_id: str) -> List[Dict[str, Any]]:
    owner_user_id = get_recovery_owner_user_id()
    service = init_drive(owner_user_id)

    items = []
    page_token = None

    while True:
        result = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, size, webViewLink, webContentLink, createdTime, modifiedTime)",
            pageSize=100,
            pageToken=page_token
        ).execute()

        items.extend(result.get("files", []) or [])
        page_token = result.get("nextPageToken")

        if not page_token:
            break

    return items


def list_user_encrypted_backup_files(target_user_id: str) -> List[Dict[str, Any]]:
    user_folder_id = get_or_create_user_recovery_folder(target_user_id)
    found = []

    def walk(folder_id: str, path_prefix: str = ""):
        for item in list_child_items(folder_id):
            name = str(item.get("name", "") or "")
            mime_type = str(item.get("mimeType", "") or "")

            current_path = f"{path_prefix}/{name}" if path_prefix else name

            if mime_type == "application/vnd.google-apps.folder":
                walk(item.get("id", ""), current_path)
            elif name.lower().endswith(".enc"):
                row = dict(item)
                row["path"] = current_path
                found.append(row)

    walk(user_folder_id)

    found.sort(key=lambda x: str(x.get("modifiedTime", "") or ""), reverse=True)
    return found


def download_backup_file_text(file_id: str) -> str:
    return download_recovery_file_text(file_id)


def replace_backup_file_text(file_id: str, text_content: str) -> Dict[str, Any]:
    owner_user_id = get_recovery_owner_user_id()
    service = init_drive(owner_user_id)

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".enc") as f:
        f.write(str(text_content or ""))
        temp_path = f.name

    try:
        media = MediaFileUpload(
            temp_path,
            mimetype="application/octet-stream",
            resumable=False
        )

        updated = service.files().update(
            fileId=str(file_id).strip(),
            media_body=media,
            fields="id, name, mimeType, size, webViewLink, webContentLink, modifiedTime"
        ).execute()

        return updated
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass
