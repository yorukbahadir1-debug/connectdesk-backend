import base64
import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken


PBKDF2_ITERATIONS = 390000
BACKUP_PAYLOAD_VERSION = "connectdesk-recovery-v1"


def generate_salt() -> str:
    return secrets.token_urlsafe(24)


def _derive_raw_key(password: str, salt: str, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    password = str(password or "")
    salt = str(salt or "")

    if not password:
        raise ValueError("Yedekleme sifresi bos olamaz.")

    if not salt:
        raise ValueError("Salt bos olamaz.")

    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations)
    )


def derive_fernet_key(password: str, salt: str, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    raw_key = _derive_raw_key(password, salt, iterations)
    return base64.urlsafe_b64encode(raw_key)


def hash_backup_password(password: str, salt: Optional[str] = None) -> str:
    salt = str(salt or generate_salt())
    raw_hash = _derive_raw_key(password, salt, PBKDF2_ITERATIONS)
    encoded_hash = base64.urlsafe_b64encode(raw_hash).decode("utf-8")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${encoded_hash}"


def verify_backup_password(password: str, stored_hash: str) -> bool:
    stored_hash = str(stored_hash or "").strip()

    if not stored_hash:
        return False

    try:
        algorithm, iterations, salt, expected_hash = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        raw_hash = _derive_raw_key(password, salt, int(iterations))
        actual_hash = base64.urlsafe_b64encode(raw_hash).decode("utf-8")
        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


def encrypt_bytes(data: bytes, password: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    salt = generate_salt()
    key = derive_fernet_key(password, salt)
    token = Fernet(key).encrypt(data)

    return {
        "version": BACKUP_PAYLOAD_VERSION,
        "encryption": "fernet",
        "kdf": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt,
        "metadata": metadata or {},
        "token": token.decode("utf-8")
    }


def decrypt_bytes(payload: Dict[str, Any], password: str) -> bytes:
    if not isinstance(payload, dict):
        raise ValueError("Yedek dosyasi formati hatali.")

    if payload.get("version") != BACKUP_PAYLOAD_VERSION:
        raise ValueError("Desteklenmeyen yedek surumu.")

    salt = str(payload.get("salt", "") or "")
    iterations = int(payload.get("iterations", PBKDF2_ITERATIONS))
    token = str(payload.get("token", "") or "")

    key = derive_fernet_key(password, salt, iterations)

    try:
        return Fernet(key).decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Yedekleme sifresi hatali veya yedek dosyasi bozuk.") from exc


def encrypt_json(data: Dict[str, Any], password: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    return encrypt_bytes(raw, password, metadata=metadata)


def decrypt_json(payload: Dict[str, Any], password: str) -> Dict[str, Any]:
    raw = decrypt_bytes(payload, password)
    return json.loads(raw.decode("utf-8"))


def encrypt_file_to_temp(file_path: str, password: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    import tempfile

    with open(file_path, "rb") as f:
        encrypted_payload = encrypt_bytes(f.read(), password, metadata=metadata)

    fd, temp_path = tempfile.mkstemp(prefix="connectdesk_recovery_", suffix=".enc")
    os.close(fd)

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(encrypted_payload, f, ensure_ascii=False, indent=2)

    return temp_path


def reencrypt_payload_text(encrypted_text: str, old_password: str, new_password: str) -> str:
    try:
        payload = json.loads(str(encrypted_text or ""))
    except Exception as exc:
        raise ValueError("Yedek dosyasi JSON formatinda degil veya bozuk.") from exc

    metadata = payload.get("metadata", {})

    if not isinstance(metadata, dict):
        metadata = {}

    raw_data = decrypt_bytes(payload, old_password)
    new_payload = encrypt_bytes(raw_data, new_password, metadata=metadata)

    return json.dumps(new_payload, ensure_ascii=False, indent=2)
