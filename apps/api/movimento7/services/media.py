import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredMedia:
    provider: str
    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str


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
    """Contrato da integração opcional; ativação depende de OAuth e chave de criptografia."""

    def store(self, content: bytes, safe_suffix: str, mime_type: str) -> StoredMedia:
        raise RuntimeError("Google Drive não configurado")

    def delete(self, storage_key: str) -> None:
        raise RuntimeError("Google Drive não configurado")
