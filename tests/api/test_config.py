from movimento7.config import Config


def production_config():
    class ProductionConfig(Config):
        APP_ENV = "production"
        SQLALCHEMY_DATABASE_URI = "postgresql+psycopg://user:password@localhost/movimento7"
        MEDIA_PROVIDER = "google_drive"
        EMAIL_DELIVERY_MODE = "log"

    return ProductionConfig


def test_production_config_requires_gallery_drive_root(monkeypatch):
    for name, value in {
        "SECRET_KEY": "production-secret-value",
        "DATABASE_URL": "postgresql+psycopg://user:password@localhost/movimento7",
        "PUBLIC_BASE_URL": "https://movimento7.com.br",
        "MEDIA_TOKEN_ENCRYPTION_KEY": "fernet-key",
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
        "GOOGLE_DRIVE_PRODUCT_FOLDER_ID": "products-root",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GOOGLE_DRIVE_GALLERY_FOLDER_ID", raising=False)

    try:
        production_config().validate()
    except RuntimeError as error:
        assert "GOOGLE_DRIVE_GALLERY_FOLDER_ID" in str(error)
    else:
        raise AssertionError("A configuração sem raiz da galeria deveria falhar")
