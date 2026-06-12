import os
import mimetypes

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = "ConnectDesk_Dosyalar"

OAUTH_CLIENT_FILE = "oauth_client.json"
TOKEN_FILE = "token_drive.json"

drive_service = None


def init_drive():
    global drive_service

    if drive_service is not None:
        return drive_service

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not os.path.exists(OAUTH_CLIENT_FILE):
            raise FileNotFoundError(
                "oauth_client.json bulunamadi. Backend klasorune koy."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            OAUTH_CLIENT_FILE,
            SCOPES
        )

        creds = flow.run_local_server(
            port=0,
            prompt="consent"
        )

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    drive_service = build("drive", "v3", credentials=creds)
    return drive_service


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


def make_file_public(file_id: str):
    service = init_drive()

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


def find_folder_by_name(name: str, parent_id: str = None):
    service = init_drive()

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


def create_folder(name: str, parent_id: str = None):
    service = init_drive()

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


def get_or_create_root_folder():
    folder_id = find_folder_by_name(ROOT_FOLDER_NAME)

    if folder_id:
        return folder_id

    return create_folder(ROOT_FOLDER_NAME)


def get_or_create_contact_folder(contact_name: str, contact_id: str):
    root_folder_id = get_or_create_root_folder()

    folder_name = f"{safe_drive_name(contact_name)}_{contact_id}"

    folder_id = find_folder_by_name(folder_name, root_folder_id)

    if folder_id:
        return folder_id

    return create_folder(folder_name, root_folder_id)


def list_files_in_folder(folder_id: str):
    service = init_drive()

    query = f"'{folder_id}' in parents and trashed=false"

    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, webViewLink, webContentLink, thumbnailLink, modifiedTime)",
        orderBy="modifiedTime desc"
    ).execute()

    files = result.get("files", [])

    for item in files:
        if item.get("id"):
            make_file_public(item["id"])
            enrich_file(item)

    return files


def upload_file_to_folder(file_path: str, folder_id: str):
    service = init_drive()

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
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink"
    ).execute()

    make_file_public(uploaded_file["id"])

    uploaded_file = service.files().get(
        fileId=uploaded_file["id"],
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink"
    ).execute()

    return enrich_file(uploaded_file)


def delete_drive_file(file_id: str):
    service = init_drive()

    service.files().delete(
        fileId=file_id
    ).execute()


def replace_file_content(file_id: str, file_path: str):
    service = init_drive()

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
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink"
    ).execute()

    make_file_public(file_id)

    updated_file = service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, webViewLink, webContentLink, thumbnailLink"
    ).execute()

    return enrich_file(updated_file)