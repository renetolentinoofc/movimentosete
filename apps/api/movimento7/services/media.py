import hashlib
import io
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


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
    """Contrato da integração opcional; ativação depende de OAuth e chave de criptografia."""

    def store(self, content: bytes, safe_suffix: str, mime_type: str) -> StoredMedia:
        raise RuntimeError("Google Drive não configurado")

    def delete(self, storage_key: str) -> None:
        raise RuntimeError("Google Drive não configurado")
