import hashlib
import io
from urllib.parse import urlparse
from uuid import UUID

from movimento7.extensions import db
from movimento7.models import (
    AdminUser,
    GalleryAlbum,
    GalleryMedia,
    MediaReconciliationTask,
    Permission,
    Role,
)
from movimento7.services.media import reconcile_gallery_media
from PIL import Image
from sqlalchemy import select
from werkzeug.security import generate_password_hash


def create_gallery_context(app):
    with app.app_context():
        permission = Permission(slug="gallery.manage", description="Administrar galeria")
        role = Role(slug="editor", name="Editor", permissions=[permission])
        admin = AdminUser(
            email="gallery@example.test",
            name="Editora da Galeria",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        album = GalleryAlbum(title="Edição 01", slug="edicao-01", status="draft")
        db.session.add_all([admin, album])
        db.session.commit()
        return str(album.id)


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "gallery@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def image_upload():
    content = io.BytesIO()
    Image.new("RGB", (640, 480), (12, 104, 94)).save(content, format="PNG")
    content.seek(0)
    return content


def test_gallery_media_upload_processes_image_and_lists_it(app, client, tmp_path, monkeypatch):
    album_id = create_gallery_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)

    response = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={
            "file": (image_upload(), "evento.png"),
            "title": "Abertura da edição",
            "category": "Eventos",
            "alt_text": "Público na abertura da edição 01",
            "caption": "Abertura da primeira edição.",
            "credit": "Foto: Movimento 7",
        },
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    payload = response.json["data"]
    assert payload["status"] == "draft"
    assert payload["width"] == 640
    assert payload["height"] == 480
    assert payload["display_order"] == 0
    with app.app_context():
        media = db.session.get(GalleryMedia, UUID(payload["id"]))
        stored = tmp_path / "uploads" / "gallery" / media.storage_key
        assert stored.is_file()
        assert media.album_id == UUID(album_id)

    listing = client.get(f"/api/v1/admin/gallery/albums/{album_id}/media")
    assert listing.status_code == 200
    assert listing.json["data"][0]["title"] == "Abertura da edição"


def test_gallery_media_upload_requires_metadata(app, client):
    album_id = create_gallery_context(app)
    csrf = login(client)

    response = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={"file": (image_upload(), "evento.png")},
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"


def test_gallery_media_upload_rejects_duplicate_image(app, client, tmp_path, monkeypatch):
    album_id = create_gallery_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)
    form = {
        "title": "Abertura da edição",
        "category": "Eventos",
        "alt_text": "Público na abertura da edição 01",
    }
    first = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={**form, "file": (image_upload(), "evento.png")},
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )
    second = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={**form, "file": (image_upload(), "evento-outra.png")},
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json["error"]["code"] == "duplicate_media"


def test_gallery_order_cannot_move_media_between_albums(app, client):
    album_id = create_gallery_context(app)
    csrf = login(client)
    with app.app_context():
        other_album = GalleryAlbum(title="Edição 02", slug="edicao-02", status="draft")
        first = GalleryMedia(
            album_id=UUID(album_id), category="Eventos", provider="local", storage_key="one.webp",
            safe_name="one.webp", media_type="image", mime_type="image/webp", size_bytes=1,
            width=1, height=1, sha256="1" * 64, title="Um", alt_text="Um", display_order=0,
            status="draft", reconciliation_status="completed",
        )
        db.session.add(other_album)
        db.session.flush()
        foreign = GalleryMedia(
            album_id=other_album.id, category="Eventos", provider="local", storage_key="two.webp",
            safe_name="two.webp", media_type="image", mime_type="image/webp", size_bytes=1,
            width=1, height=1, sha256="2" * 64, title="Dois", alt_text="Dois", display_order=0,
            status="draft", reconciliation_status="completed",
        )
        db.session.add_all([first, foreign])
        db.session.commit()
        first_id, foreign_id = str(first.id), str(foreign.id)

    rejected = client.patch(
        "/api/v1/admin/gallery/order",
        json={"album_id": album_id, "ids": [foreign_id]},
        headers={"X-CSRF-Token": csrf},
    )
    accepted = client.patch(
        "/api/v1/admin/gallery/order",
        json={"album_id": album_id, "ids": [first_id]},
        headers={"X-CSRF-Token": csrf},
    )

    assert rejected.status_code == 422
    assert rejected.json["error"]["code"] == "validation_error"
    assert accepted.status_code == 200


def test_gallery_publication_requires_media_and_exposes_published_content(
    app, client, tmp_path, monkeypatch
):
    album_id = create_gallery_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)

    blocked = client.patch(
        f"/api/v1/admin/gallery/albums/{album_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )
    assert blocked.status_code == 422

    uploaded = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={
            "file": (image_upload(), "evento.png"),
            "title": "Abertura da edição",
            "category": "Eventos",
            "alt_text": "Público na abertura da edição 01",
        },
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )
    media_id = uploaded.json["data"]["id"]
    published_media = client.patch(
        f"/api/v1/admin/gallery/media/{media_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )
    published_album = client.patch(
        f"/api/v1/admin/gallery/albums/{album_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )

    assert published_media.status_code == 200
    assert published_album.status_code == 200
    public = client.get("/api/v1/gallery")
    assert public.status_code == 200
    assert public.json["data"][0]["title"] == "Abertura da edição"
    public_url = public.json["data"][0]["url"]
    assert public_url.endswith(f"/media/gallery/{media_id}")
    served = client.get(urlparse(public_url).path.replace("/media/", "/api/v1/media/", 1))
    assert served.status_code == 200
    assert served.mimetype == "image/webp"
    assert served.data


def test_gallery_media_file_is_not_public_before_publication(app, client, tmp_path, monkeypatch):
    album_id = create_gallery_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)
    uploaded = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={
            "file": (image_upload(), "evento.png"),
            "title": "Abertura da edição",
            "category": "Eventos",
            "alt_text": "Público na abertura da edição 01",
        },
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )
    media_id = uploaded.json["data"]["id"]

    response = client.get(f"/api/v1/media/gallery/{media_id}")

    assert response.status_code == 404


def test_gallery_reconciliation_creates_task_for_missing_local_file(app, client, tmp_path, monkeypatch):
    album_id = create_gallery_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)
    uploaded = client.post(
        f"/api/v1/admin/gallery/albums/{album_id}/media/upload",
        data={
            "file": (image_upload(), "evento.png"),
            "title": "Abertura da edição",
            "category": "Eventos",
            "alt_text": "Público na abertura da edição 01",
        },
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )
    media_id = UUID(uploaded.json["data"]["id"])
    with app.app_context():
        media = db.session.get(GalleryMedia, media_id)
        (tmp_path / "uploads" / "gallery" / media.storage_key).unlink()

    response = client.post(
        "/api/v1/admin/gallery/reconcile",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json["data"]["missing"] == 1
    with app.app_context():
        media = db.session.get(GalleryMedia, media_id)
        task = db.session.scalar(
            select(MediaReconciliationTask).where(
                MediaReconciliationTask.resource_id == media_id
            )
        )
        assert media.reconciliation_status == "missing"
        assert task.action == "inspect"


def test_gallery_reconciliation_processes_all_rows_in_batches(app, tmp_path, monkeypatch):
    album_id = UUID(create_gallery_context(app))
    monkeypatch.chdir(tmp_path)
    gallery_root = tmp_path / "uploads" / "gallery"
    gallery_root.mkdir(parents=True)
    with app.app_context():
        rows = []
        for index in range(3):
            content = f"media-{index}".encode()
            storage_key = f"media-{index}.webp"
            (gallery_root / storage_key).write_bytes(content)
            rows.append(GalleryMedia(
                album_id=album_id,
                category="Eventos",
                provider="local",
                storage_key=storage_key,
                safe_name=storage_key,
                media_type="image",
                mime_type="image/webp",
                size_bytes=len(content),
                width=1,
                height=1,
                sha256=hashlib.sha256(content).hexdigest(),
                title=f"Mídia {index}",
                alt_text=f"Mídia {index}",
                display_order=index,
                status="published",
                reconciliation_status="pending",
            ))
        db.session.add_all(rows)
        db.session.commit()

        result = reconcile_gallery_media(limit=1)

        assert result["completed"] == 3
        assert db.session.scalar(
            select(GalleryMedia).where(GalleryMedia.reconciliation_status == "pending")
        ) is None
