import hashlib
import io
import json
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from ..extensions import db
from ..models.content import IntegrationCredential


@dataclass(frozen=True)
class StoredMedia:
    provider: str
    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ProcessedImage:
    content: bytes
    mime_type: str
    suffix: str
    width: int
    height: int


def process_portfolio_image(content: bytes) -> ProcessedImage:
    """Valida, orienta e reduz uma imagem de portfólio para WebP."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > 40_000_000:
                raise ValueError("Imagem com dimensões excessivas")
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            has_alpha = image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            )
            image = image.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=85, method=6)
            return ProcessedImage(
                content=output.getvalue(),
                mime_type="image/webp",
                suffix=".webp",
                width=image.width,
                height=image.height,
            )
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ValueError("Arquivo de imagem inválido") from error


class MediaProvider(ABC):
    @abstractmethod
    def store(self, content: bytes, safe_suffix: str, mime_type: str) -> StoredMedia:
        raise NotImplementedError

    @abstractmethod
    def delete(self, storage_key: str) -> None:
        raise NotImplementedError


class LocalMediaProvider(MediaProvider):
    def __init__(self, root: Path):
        self.root = root

    def store(self, content: bytes, safe_suffix: str, mime_type: str) -> StoredMedia:
        suffix = (
            safe_suffix.lower()
            if safe_suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".avif"}
            else ".bin"
        )
        key = f"{secrets.token_urlsafe(18)}{suffix}"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / key).write_bytes(content)
        return StoredMedia(
            "local", key, mime_type, len(content), hashlib.sha256(content).hexdigest()
        )

    def delete(self, storage_key: str) -> None:
        target = (self.root / storage_key).resolve()
        if self.root.resolve() not in target.parents:
            raise ValueError("Chave de mídia inválida")
        target.unlink(missing_ok=True)


class GoogleDriveMediaProvider(MediaProvider):
    """Armazena imagens em uma pasta do Drive autorizada via OAuth PKCE."""

    def _access_token(self) -> str:
        key = current_app.config["MEDIA_TOKEN_ENCRYPTION_KEY"]
        credential = db.session.scalar(
            select(IntegrationCredential).where(IntegrationCredential.provider == "google_drive")
        )
        if not key or not credential or credential.status != "active":
            raise RuntimeError("Google Drive não configurado")
        try:
            payload = json.loads(
                Fernet(key.encode()).decrypt(credential.encrypted_payload).decode()
            )
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("Credencial do Google Drive inválida") from error
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            timeout=15,
            data={
                "client_id": current_app.config["GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
                "refresh_token": payload["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if not response.ok or not response.json().get("access_token"):
            raise RuntimeError("Não foi possível renovar o acesso ao Google Drive")
        return response.json()["access_token"]

    def _product_folder(self, token: str, folder_name: str) -> str:
        parent = current_app.config["GOOGLE_DRIVE_PRODUCT_FOLDER_ID"]
        if not parent:
            raise RuntimeError("GOOGLE_DRIVE_PRODUCT_FOLDER_ID não configurado")
        query = (
            f"name = '{folder_name.replace(chr(39), chr(92) + chr(39))}' "
            "and mimeType = 'application/vnd.google-apps.folder' "
            f"and '{parent}' in parents and trashed = false"
        )
        response = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "fields": "files(id)", "pageSize": 1},
            timeout=15,
        )
        if not response.ok:
            raise RuntimeError("Não foi possível consultar as pastas do Google Drive")
        existing = response.json().get("files", [])
        if existing:
            return existing[0]["id"]
        created = requests.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent],
            },
            timeout=15,
        )
        if not created.ok or not created.json().get("id"):
            raise RuntimeError("Não foi possível criar a subpasta no Google Drive")
        return created.json()["id"]

    def store(
        self, content: bytes, safe_suffix: str, mime_type: str, folder_name: str | None = None
    ) -> StoredMedia:
        token = self._access_token()
        name = f"produto-{secrets.token_urlsafe(12)}{safe_suffix}"
        metadata = {"name": name, "mimeType": mime_type}
        folder = current_app.config["GOOGLE_DRIVE_PRODUCT_FOLDER_ID"]
        if folder_name:
            folder = self._product_folder(token, folder_name)
        if folder:
            metadata["parents"] = [folder]
        response = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "metadata": (None, json.dumps(metadata), "application/json"),
                "file": (name, content, mime_type),
            },
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError("O Google Drive recusou o upload")
        file_id = response.json().get("id")
        if not file_id:
            raise RuntimeError("O Google Drive não retornou o identificador do arquivo")
        permission = requests.post(
            f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "anyone", "role": "reader"},
            timeout=15,
        )
        if not permission.ok:
            raise RuntimeError("Não foi possível publicar a imagem do Drive")
        return StoredMedia(
            "google_drive",
            f"https://drive.google.com/uc?export=view&id={file_id}",
            mime_type,
            len(content),
            hashlib.sha256(content).hexdigest(),
        )

    def delete(self, storage_key: str) -> None:
        raise RuntimeError("Exclusão de mídia do Drive exige o identificador original do arquivo")
