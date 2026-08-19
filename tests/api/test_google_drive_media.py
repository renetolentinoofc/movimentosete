import json

from movimento7.services import media as media_service


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


def test_gallery_drive_folder_is_independent_from_product_folder(app, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return FakeResponse({"files": []})

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        if "upload/drive" in url:
            return FakeResponse({"id": "gallery-file-id"})
        if "permissions" in url:
            return FakeResponse({})
        return FakeResponse({"id": "gallery-album-folder-id"})

    monkeypatch.setattr(media_service.requests, "get", fake_get)
    monkeypatch.setattr(media_service.requests, "post", fake_post)
    monkeypatch.setattr(media_service.GoogleDriveMediaProvider, "_access_token", lambda self: "token")
    app.config.update(
        GOOGLE_DRIVE_PRODUCT_FOLDER_ID="products-root",
        GOOGLE_DRIVE_GALLERY_FOLDER_ID="gallery-root",
        MEDIA_TOKEN_ENCRYPTION_KEY="",
    )

    with app.app_context():
        provider = media_service.GoogleDriveMediaProvider()
        stored = provider.store(
            b"image",
            ".webp",
            "image/webp",
            folder_name="edicao-01",
            root_folder_id=app.config["GOOGLE_DRIVE_GALLERY_FOLDER_ID"],
            filename_prefix="galeria",
        )

    folder_query = calls[0][2]["params"]["q"]
    upload_call = next(call for call in calls if "upload/drive" in call[1])
    metadata = json.loads(upload_call[2]["files"]["metadata"][1])
    assert "'gallery-root' in parents" in folder_query
    assert "'products-root' in parents" not in folder_query
    assert metadata["parents"] == ["gallery-album-folder-id"]
    assert metadata["name"].startswith("galeria-")
    assert stored.storage_key.endswith("gallery-file-id")


def test_gallery_drive_lists_root_and_album_files(app, monkeypatch):
    def fake_get(url, **kwargs):
        query = kwargs["params"]["q"]
        if "mimeType = 'application/vnd.google-apps.folder'" in query:
            return FakeResponse({"files": [{"id": "album-folder-id"}]})
        if "'gallery-root' in parents" in query:
            return FakeResponse({"files": [{"id": "root-file-id"}]})
        return FakeResponse({"files": [{"id": "album-file-id"}]})

    monkeypatch.setattr(media_service.requests, "get", fake_get)
    monkeypatch.setattr(media_service.GoogleDriveMediaProvider, "_access_token", lambda self: "token")

    with app.app_context():
        files = media_service.GoogleDriveMediaProvider().list_gallery_files("gallery-root")

    assert set(files) == {"root-file-id", "album-file-id"}
