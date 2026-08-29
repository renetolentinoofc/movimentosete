import hashlib
import io
import json
import secrets
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, or_, select

from ..extensions import db
from ..models.content import GalleryMedia, IntegrationCredential, MediaReconciliationTask
from .observability import capture_exception


@dataclass(frozen=True)
class StoredMedia:
    provider: str
    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str
    provider_id: str | None = None


@dataclass(frozen=True)
class ProcessedImage:
    content: bytes
    mime_type: str
    suffix: str
    width: int
    height: int


def local_media_root() -> Path:
    return Path(current_app.config["MEDIA_LOCAL_ROOT"]).expanduser().resolve()


def gallery_media_root() -> Path:
    return local_media_root() / "gallery"


def gallery_media_url(provider: str, storage_key: str, media_id: str) -> str:
    if provider != "local":
        return storage_key
    base_url = current_app.config["MEDIA_PUBLIC_BASE_URL"].rstrip("/")
    return f"{base_url}/gallery/{quote(media_id, safe='')}"


def product_media_url(provider: str, storage_key: str, media_id: str) -> str:
    if provider != "local":
        return storage_key
    return f"/api/v1/media/products/{quote(media_id, safe='')}"


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
        capture_exception(error, context={"component": "media_image_processing"})
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
            capture_exception(error, context={"component": "google_drive_credentials"})
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

    def _named_folder(self, token: str, folder_name: str, parent: str) -> str:
        if not parent:
            raise RuntimeError("Pasta raiz do Google Drive não configurada")
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
        self,
        content: bytes,
        safe_suffix: str,
        mime_type: str,
        folder_name: str | None = None,
        root_folder_id: str | None = None,
        filename_prefix: str = "produto",
    ) -> StoredMedia:
        token = self._access_token()
        name = f"{filename_prefix}-{secrets.token_urlsafe(12)}{safe_suffix}"
        metadata = {"name": name, "mimeType": mime_type}
        folder = root_folder_id or current_app.config["GOOGLE_DRIVE_PRODUCT_FOLDER_ID"]
        if folder_name:
            folder = self._named_folder(token, folder_name, folder)
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
            provider_id=file_id,
        )

    def delete(self, storage_key: str) -> None:
        raise RuntimeError("Exclusão de mídia do Drive exige o identificador original do arquivo")

    def inspect(
        self, storage_key: str, provider_id: str | None = None
    ) -> tuple[str, str | None, str | None]:
        file_id = provider_id or parse_qs(urlparse(storage_key).query).get("id", [None])[0]
        if not file_id:
            return "error", None, "Identificador do arquivo do Google Drive ausente"
        token = self._access_token()
        response = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{quote(file_id, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "id,trashed"},
            timeout=15,
        )
        if response.status_code == 404:
            return "missing", file_id, "Arquivo não encontrado no Google Drive"
        if not response.ok:
            return "error", file_id, "Não foi possível consultar o arquivo no Google Drive"
        if response.json().get("trashed"):
            return "missing", file_id, "Arquivo enviado para a lixeira do Google Drive"
        return "completed", file_id, None

    def list_gallery_files(self, root_folder_id: str) -> list[str]:
        if not root_folder_id:
            raise RuntimeError("GOOGLE_DRIVE_GALLERY_FOLDER_ID não configurado")
        token = self._access_token()

        def list_children(parent_id: str, folders_only: bool = False) -> list[dict]:
            query = f"'{parent_id}' in parents and trashed = false"
            if folders_only:
                query += " and mimeType = 'application/vnd.google-apps.folder'"
            else:
                query += " and mimeType != 'application/vnd.google-apps.folder'"
            files: list[dict] = []
            page_token = None
            while True:
                params = {
                    "q": query,
                    "fields": "nextPageToken,files(id)",
                    "pageSize": 1000,
                }
                if page_token:
                    params["pageToken"] = page_token
                response = requests.get(
                    "https://www.googleapis.com/drive/v3/files",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=15,
                )
                if not response.ok:
                    raise RuntimeError("Não foi possível listar os arquivos do Google Drive")
                payload = response.json()
                files.extend(payload.get("files", []))
                page_token = payload.get("nextPageToken")
                if not page_token:
                    return files

        album_folders = list_children(root_folder_id, folders_only=True)
        files = list_children(root_folder_id)
        for folder in album_folders:
            files.extend(list_children(folder["id"]))
        return [item["id"] for item in files]


def reconcile_gallery_media(limit: int = 200) -> dict[str, int]:
    """Reconcile the complete catalog in bounded keyset-paginated batches."""
    batch_size = max(1, min(limit, 5000))
    counts = Counter()
    drive = (
        GoogleDriveMediaProvider()
        if db.session.scalar(
            select(GalleryMedia.id).where(
                GalleryMedia.deleted_at.is_(None), GalleryMedia.provider == "google_drive"
            ).limit(1)
        )
        or current_app.config["MEDIA_PROVIDER"] == "google_drive"
        else None
    )
    known_drive_ids: set[str] = set()
    last_created_at = None
    last_id = None
    while True:
        query = (
            select(GalleryMedia, func.count(GalleryMedia.sha256).over(
                partition_by=GalleryMedia.sha256
            ).label("hash_count"))
            .where(GalleryMedia.deleted_at.is_(None))
            .order_by(GalleryMedia.created_at, GalleryMedia.id)
            .limit(batch_size)
        )
        if last_created_at is not None and last_id is not None:
            query = query.where(or_(
                GalleryMedia.created_at > last_created_at,
                (GalleryMedia.created_at == last_created_at) & (GalleryMedia.id > last_id),
            ))
        batch = db.session.execute(query).all()
        if not batch:
            break
        for row, hash_count in batch:
            status = "completed"
            error = None
            if hash_count > 1:
                status = "duplicate"
                error = "Mais de uma mídia ativa possui o mesmo checksum"
            if row.provider == "local":
                target = (gallery_media_root() / row.storage_key).resolve()
                root = gallery_media_root()
                if root not in target.parents or not target.is_file():
                    status, error = "missing", "Arquivo local não encontrado"
                elif hashlib.sha256(target.read_bytes()).hexdigest() != row.sha256:
                    status, error = (
                        "mismatch", "Checksum do arquivo local não corresponde ao catálogo"
                    )
            elif row.provider == "google_drive" and drive:
                status, row.provider_id, error = drive.inspect(row.storage_key, row.provider_id)
                if row.provider_id:
                    known_drive_ids.add(row.provider_id)
            elif row.provider not in {"local", "google_drive"}:
                status, error = "error", "Provedor de mídia não suportado"
            row.reconciliation_status = status
            counts[status] += 1
            existing = db.session.scalar(
                select(MediaReconciliationTask).where(
                    MediaReconciliationTask.resource_type == "gallery_media",
                    MediaReconciliationTask.resource_id == row.id,
                    MediaReconciliationTask.action == "inspect",
                    MediaReconciliationTask.status == "pending",
                )
            )
            if status == "completed":
                if existing:
                    existing.status = "resolved"
                    existing.last_error = None
            elif existing:
                existing.attempts += 1
                existing.last_error = error
            else:
                db.session.add(MediaReconciliationTask(
                    provider=row.provider,
                    resource_type="gallery_media",
                    resource_id=row.id,
                    storage_key=row.storage_key,
                    action="inspect",
                    status="pending",
                    attempts=1,
                    last_error=error,
                ))
        last_created_at = batch[-1][0].created_at
        last_id = batch[-1][0].id
        db.session.commit()
    if drive:
        orphan_ids = set(
            drive.list_gallery_files(current_app.config["GOOGLE_DRIVE_GALLERY_FOLDER_ID"])
        ) - known_drive_ids
        for file_id in orphan_ids:
            storage_key = f"https://drive.google.com/uc?export=view&id={file_id}"
            existing = db.session.scalar(
                select(MediaReconciliationTask).where(
                    MediaReconciliationTask.provider == "google_drive",
                    MediaReconciliationTask.resource_type == "gallery_media",
                    MediaReconciliationTask.storage_key == storage_key,
                    MediaReconciliationTask.action == "orphan",
                    MediaReconciliationTask.status == "pending",
                )
            )
            if existing:
                existing.attempts += 1
            else:
                db.session.add(MediaReconciliationTask(
                    provider="google_drive",
                    resource_type="gallery_media",
                    storage_key=storage_key,
                    action="orphan",
                    status="pending",
                    attempts=1,
                    last_error="Arquivo no Drive sem registro correspondente na galeria",
                ))
            counts["orphan"] += 1
    db.session.commit()
    return dict(counts)
