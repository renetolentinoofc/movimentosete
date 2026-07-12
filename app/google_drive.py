"""Integração do Movimento 7 com o Google Drive."""

from __future__ import annotations

import base64
import hashlib
import io
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from PIL import Image, ImageOps

from . import db
from .models import AppSetting

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
REFRESH_TOKEN_KEY = "google_drive_refresh_token"


def _fernet() -> Fernet:
    """Deriva uma chave de criptografia estável a partir da SECRET_KEY."""
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    derived = hashlib.sha256(secret).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def save_refresh_token(refresh_token: str) -> None:
    encrypted = _fernet().encrypt(refresh_token.encode("utf-8")).decode("utf-8")
    setting = db.session.get(AppSetting, REFRESH_TOKEN_KEY)
    if setting is None:
        setting = AppSetting(key=REFRESH_TOKEN_KEY, value=encrypted)
        db.session.add(setting)
    else:
        setting.value = encrypted
    db.session.commit()


def get_refresh_token() -> str:
    """Lê o token persistido; aceita variável de ambiente como fallback."""
    setting = db.session.get(AppSetting, REFRESH_TOKEN_KEY)
    if setting:
        try:
            return _fernet().decrypt(setting.value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(
                "O token salvo não pôde ser descriptografado. A SECRET_KEY pode ter mudado."
            ) from exc

    token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
    if token:
        return token

    raise RuntimeError("Google Drive ainda não foi conectado.")


def google_drive_is_connected() -> bool:
    try:
        return bool(get_refresh_token())
    except RuntimeError:
        return False


def clear_refresh_token() -> None:
    """Remove a autorização persistida para permitir uma nova conexão."""
    setting = db.session.get(AppSetting, REFRESH_TOKEN_KEY)
    if setting is not None:
        db.session.delete(setting)
        db.session.commit()


def get_gallery_folder_info() -> dict[str, str]:
    """Confirma que a pasta existe e que a conta autorizada consegue acessá-la."""
    folder_id = get_gallery_folder_id()
    result = (
        get_drive_service()
        .files()
        .get(fileId=folder_id, fields="id,name,mimeType,trashed")
        .execute()
    )
    if result.get("trashed"):
        raise RuntimeError("A pasta configurada está na lixeira do Google Drive.")
    if result.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError("GOOGLE_DRIVE_GALLERY_FOLDER_ID não aponta para uma pasta.")
    return {"id": result["id"], "name": result.get("name", "Galeria")}


def get_google_credentials() -> Credentials:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    refresh_token = get_refresh_token()

    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if missing:
        raise RuntimeError("Variáveis do Google ausentes: " + ", ".join(missing))

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=DRIVE_SCOPES,
    )


def get_drive_service() -> Any:
    return build("drive", "v3", credentials=get_google_credentials(), cache_discovery=False)


def get_gallery_folder_id() -> str:
    folder_id = os.getenv("GOOGLE_DRIVE_GALLERY_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("GOOGLE_DRIVE_GALLERY_FOLDER_ID não foi configurado.")
    return folder_id


def optimize_image(uploaded_file) -> tuple[io.BytesIO, str]:
    """Corrige orientação, reduz dimensões e converte a foto para WebP."""
    uploaded_file.stream.seek(0)
    with Image.open(uploaded_file.stream) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=84, method=6)
    output.seek(0)
    return output, "image/webp"


def upload_gallery_image(uploaded_file, title: str) -> dict[str, str]:
    image_stream, mime_type = optimize_image(uploaded_file)
    folder = get_gallery_folder_info()
    service = get_drive_service()
    metadata = {
        "name": f"{title.strip() or 'foto-galeria'}.webp",
        "parents": [folder["id"]],
    }
    media = MediaIoBaseUpload(image_stream, mimetype=mime_type, resumable=False)
    result = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,mimeType")
        .execute()
    )
    return {"id": result["id"], "mime_type": result.get("mimeType", mime_type)}


def download_drive_image(file_id: str) -> io.BytesIO:
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    output.seek(0)
    return output


def delete_drive_image(file_id: str) -> None:
    get_drive_service().files().delete(fileId=file_id).execute()
