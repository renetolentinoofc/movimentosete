from __future__ import annotations

import os
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Permite criar e administrar apenas arquivos utilizados pela aplicação.
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]


def get_google_credentials() -> Credentials:
    """
    Cria as credenciais OAuth usando as variáveis de ambiente.

    O access token é renovado automaticamente usando o refresh token.
    Nenhuma credencial deve ser escrita diretamente no código.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()

    missing = []

    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")

    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")

    if not refresh_token:
        missing.append("GOOGLE_REFRESH_TOKEN")

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
    """
    Retorna um cliente autenticado da Google Drive API v3.
    """
    credentials = get_google_credentials()

    return build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def get_gallery_folder_id() -> str:
    """
    Retorna o ID da pasta configurada para a galeria.
    """
    folder_id = os.getenv(
        "GOOGLE_DRIVE_GALLERY_FOLDER_ID",
        "",
    ).strip()

    if not folder_id:
        raise RuntimeError("GOOGLE_DRIVE_GALLERY_FOLDER_ID não foi configurado.")

    return folder_id
