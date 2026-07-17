import os
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
import json
import mimetypes
import io
from typing import Optional, Dict, Any, Tuple

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request


SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = os.getenv("DRIVE_ROOT_FOLDER_NAME", "ConnectDesk_Dosyalar")
OAUTH_CLIENT_FILE = "oauth_client.json"


def _load_json_from_env(env_name: str):
    value = os.getenv(env_name, "").strip()

    if not value:
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{env_name} JSON formati hatali.") from exc


def _load_oauth_client_config() -> Dict[str, Any]:
    config = _load_json_from_env("OAUTH_CLIENT_JSON")

    if config:
        return config

    if os.path.exists(OAUTH_CLIENT_FILE):
        with open(OAUTH_CLIENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    raise FileNotFoundError(
        "Google OAuth bilgisi bulunamadi. Render Environment icin OAUTH_CLIENT_JSON eklenmeli."
    )


def get_public_base_url() -> str:
    base_url = (
        os.getenv("PUBLIC_API_BASE_URL", "")
        or os.getenv("RENDER_EXTERNAL_URL", "")
        or "http://127.0.0.1:8000"
    )
    return base_url.strip().rstrip("/")


def get_redirect_uri() -> str:
    return (
        os.getenv("OAUTH_REDIRECT_URI", "").strip()
        or f"{get_public_base_url()}/google/callback"
    )


def _create_flow(state: Optional[str] = None) -> Flow:
    flow = Flow.from_client_config(
        _load_oauth_client_config(),
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=False
    )
    flow.redirect_uri = get_redirect_uri()
    return flow


def create_google_auth_url(user_id: str) -> str:
    user_id = str(user_id).strip()

    if not user_id:
        raise ValueError("Kullanici id bos olamaz.")

    flow = _create_flow(state=user_id)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    return auth_url


def finish_google_callback(authorization_response_url: str, state: str) -> Dict[str, Any]:
    user_id = str(state or "").strip()

    if not user_id:
        raise ValueError("Google callback state/user_id bos geldi.")

    flow = _create_flow(state=user_id)
    flow.fetch_token(authorization_response=authorization_response_url)

    creds = flow.credentials
    token_info = json.loads(creds.to_json())

    service = build("drive", "v3", credentials=creds)

    drive_email = ""
    drive_display_name = ""

    try:
        about = service.about().get(fields="user(emailAddress,displayName)").execute()
        drive_user = about.get("user", {}) or {}
        drive_email = str(drive_user.get("emailAddress", "") or "")
        drive_display_name = str(drive_user.get("displayName", "") or "")
    except Exception:
        pass

    from services.firebase_service import save_user_drive_token

    save_user_drive_token(
        user_id=user_id,
        token_json=token_info,
        drive_email=drive_email,
        drive_display_name=drive_display_name
    )

    return {
        "success": True,
        "user_id": user_id,
        "drive_email": drive_email,
        "drive_display_name": drive_display_name
    }


def build_credentials_from_token(user_id: str) -> Credentials:
    from services.firebase_service import get_user_drive_token, save_user_drive_token

    token_info = get_user_drive_token(user_id)

    if not token_info:
        raise RuntimeError(
            "Google Drive bagli degil. Uygulamada 'Google Drive Bagla' butonuna basin."
        )

    creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_user_drive_token(
            user_id=user_id,
            token_json=json.loads(creds.to_json())
        )

    if not creds or not creds.valid:
        raise RuntimeError(
            "Google Drive oturumu gecersiz. Uygulamada Google Drive'i yeniden baglayin."
        )

    return creds


def init_drive(user_id: str):
    creds = build_credentials_from_token(user_id)
    return build("drive", "v3", credentials=creds)


def safe_drive_name(name: str):
    name = str(name).strip()

    invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]

    for char in invalid_chars:
        name = name.replace(char, "-")

    if not name:
        name = "Adsiz"

    return name


def public_view_url(file_id: str):
    return f"https://drive.google.com/uc?export=view&id={file_id}"


def public_download_url(file_id: str):
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def make_file_public(user_id: str, file_id: str):
    make_public = str(os.getenv("MAKE_FILES_PUBLIC", "true")).strip().lower()

    if make_public in ("0", "false", "no", "hayir"):
        return

    service = init_drive(user_id)

    try:
        service.permissions().create(
            fileId=file_id,
            body={
                "type": "anyone",
                "role": "reader"
            },
            fields="id"
        ).execute()
    except Exception:
        pass


def enrich_file(file_data: dict):
    file_id = file_data.get("id", "")

    if file_id:
        file_data["view_url"] = public_view_url(file_id)
        file_data["download_url"] = public_download_url(file_id)

    return file_data


def find_folder_by_name(user_id: str, name: str, parent_id: str = None):
    service = init_drive(user_id)

    safe_name = name.replace("'", "\\'")

    query = f"name='{safe_name}' and mimeType='{FOLDER_MIME_TYPE}' and trashed=false"

    if parent_id:
        query += f" and '{parent_id}' in parents"

    result = service.files().list(
        q=query,
        fields="files(id, name)"
    ).execute()

    files = result.get("files", [])

    if files:
        return files[0]["id"]

    return None


def create_folder(user_id: str, name: str, parent_id: str = None):
    service = init_drive(user_id)

    metadata = {
        "name": name,
        "mimeType": FOLDER_MIME_TYPE
    }

    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=metadata,
        fields="id, name"
    ).execute()

    return folder["id"]


def rename_drive_file(user_id: str, file_id: str, new_name: str):
    file_id = str(file_id or "").strip()
    new_name = safe_drive_name(new_name)

    if not file_id:
        return None

    service = init_drive(user_id)

    return service.files().update(
        fileId=file_id,
        body={"name": new_name},
        fields="id, name, mimeType, webViewLink, webContentLink"
    ).execute()


def get_or_create_root_folder(user_id: str):
    folder_id = find_folder_by_name(user_id, ROOT_FOLDER_NAME)

    if folder_id:
        return folder_id

    return create_folder(user_id, ROOT_FOLDER_NAME)


def get_or_create_contact_folder(user_id: str, contact_name: str, contact_id: str):
    root_folder_id = get_or_create_root_folder(user_id)

    folder_name = f"{safe_drive_name(contact_name)}_{contact_id}"

    folder_id = find_folder_by_name(user_id, folder_name, root_folder_id)

    if folder_id:
        return folder_id

    return create_folder(user_id, folder_name, root_folder_id)


def list_files_in_folder(user_id: str, folder_id: str):
    service = init_drive(user_id)

    query = f"'{folder_id}' in parents and trashed=false"

    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime)",
        orderBy="modifiedTime desc"
    ).execute()

    files = result.get("files", [])

    for item in files:
        if item.get("id"):
            # Hız için listeleme sırasında her dosyaya tekrar public izin basmıyoruz.
            # Yükleme sırasında public izin zaten veriliyor; burada sadece linkleri zenginleştiriyoruz.
            enrich_file(item)

    return files


def upload_file_to_folder(user_id: str, file_path: str, folder_id: str):
    service = init_drive(user_id)

    file_name = os.path.basename(file_path)

    mime_type, _ = mimetypes.guess_type(file_path)

    if mime_type is None:
        mime_type = "application/octet-stream"

    metadata = {
        "name": file_name,
        "parents": [folder_id]
    }

    media = MediaFileUpload(
        file_path,
        mimetype=mime_type,
        resumable=False
    )

    uploaded_file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime, size"
    ).execute()

    make_file_public(user_id, uploaded_file["id"])

    uploaded_file = service.files().get(
        fileId=uploaded_file["id"],
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime, size"
    ).execute()

    return enrich_file(uploaded_file)


def delete_drive_file(user_id: str, file_id: str):
    service = init_drive(user_id)

    service.files().delete(
        fileId=file_id
    ).execute()


def replace_file_content(user_id: str, file_id: str, file_path: str):
    service = init_drive(user_id)

    mime_type, _ = mimetypes.guess_type(file_path)

    if mime_type is None:
        mime_type = "application/octet-stream"

    media = MediaFileUpload(
        file_path,
        mimetype=mime_type,
        resumable=False
    )

    updated_file = service.files().update(
        fileId=file_id,
        media_body=media,
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime, size"
    ).execute()

    make_file_public(user_id, file_id)

    updated_file = service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime, size"
    ).execute()

    return enrich_file(updated_file)



def download_drive_file_bytes(user_id: str, file_id: str):
    file_id = str(file_id or "").strip()

    if not file_id:
        raise ValueError("Dosya id bos olamaz.")

    service = init_drive(user_id)

    metadata = service.files().get(
        fileId=file_id,
        fields="id, name, mimeType"
    ).execute()

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False

    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)

    return {
        "id": metadata.get("id", file_id),
        "name": metadata.get("name", ""),
        "mimeType": metadata.get("mimeType", "application/octet-stream"),
        "content": buffer.getvalue()
    }


# ============================================================
# CONNECTDESK BACKUP DRIVE HELPERS
# ============================================================

def get_or_create_contact_backup_folder(user_id: str, contact_name: str, contact_id: str):
    contact_folder_id = get_or_create_contact_folder(user_id, contact_name, contact_id)

    backup_folder_name = "__BACKUP__"

    folder_id = find_folder_by_name(user_id, backup_folder_name, contact_folder_id)

    if folder_id:
        return folder_id

    return create_folder(user_id, backup_folder_name, contact_folder_id)


def upload_file_to_folder_as(user_id: str, file_path: str, folder_id: str, drive_file_name: str):
    service = init_drive(user_id)

    mime_type, _ = mimetypes.guess_type(file_path)

    if mime_type is None:
        mime_type = "application/octet-stream"

    metadata = {
        "name": str(drive_file_name or os.path.basename(file_path)).strip(),
        "parents": [folder_id]
    }

    media = MediaFileUpload(
        file_path,
        mimetype=mime_type,
        resumable=False
    )

    uploaded_file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime, size"
    ).execute()

    make_file_public(user_id, uploaded_file["id"])

    uploaded_file = service.files().get(
        fileId=uploaded_file["id"],
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink, createdTime, modifiedTime, size"
    ).execute()

    return enrich_file(uploaded_file)


def upload_file_with_backup(user_id: str, file_path: str, original_folder_id: str, backup_folder_id: str, original_filename: str = ""):
    original_name = str(original_filename or os.path.basename(file_path)).strip() or os.path.basename(file_path)

    original_file = upload_file_to_folder_as(
        user_id=user_id,
        file_path=file_path,
        folder_id=original_folder_id,
        drive_file_name=original_name
    )

    backup_file = upload_file_to_folder_as(
        user_id=user_id,
        file_path=file_path,
        folder_id=backup_folder_id,
        drive_file_name=f"BACKUP_{original_name}"
    )

    return {
        "original": original_file,
        "backup": backup_file
    }


def upload_text_backup_file(user_id: str, folder_id: str, file_name: str, text_content: str):
    import tempfile

    safe_name = str(file_name or "recovery_backup.json").strip()

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as f:
        f.write(str(text_content or ""))
        temp_path = f.name

    try:
        return upload_file_to_folder_as(
            user_id=user_id,
            file_path=temp_path,
            folder_id=folder_id,
            drive_file_name=safe_name
        )
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


def get_or_create_user_recovery_folder(user_id: str):
    root_folder_id = get_or_create_root_folder(user_id)

    folder_name = "__RECOVERY__"

    folder_id = find_folder_by_name(user_id, folder_name, root_folder_id)

    if folder_id:
        return folder_id

    return create_folder(user_id, folder_name, root_folder_id)
