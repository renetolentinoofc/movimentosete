import os
from dataclasses import dataclass


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    env: str
    public_base_url: str
    auction_bidding_enabled: bool
    payment_provider: str
    media_provider: str


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "sqlite:///movimento7-development.sqlite3")
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+psycopg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    return value


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    APP_VERSION = os.getenv("APP_VERSION", "0.1.0-local")
    GIT_COMMIT = os.getenv("GIT_COMMIT", os.getenv("RENDER_GIT_COMMIT", "local"))
    DEPLOYED_AT = os.getenv("DEPLOYED_AT", "")
    SECRET_KEY = os.getenv("SECRET_KEY", "local-development-only-change-me")
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")
    CORS_ORIGINS = [
        item.strip()
        for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if item.strip()
    ]
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", APP_ENV == "production")
    AUCTION_BIDDING_ENABLED = env_bool("AUCTION_BIDDING_ENABLED", False)
    PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "manual")
    MEDIA_PROVIDER = os.getenv("MEDIA_PROVIDER", "local")
    MEDIA_LOCAL_ROOT = os.getenv("MEDIA_LOCAL_ROOT", "./uploads")
    MEDIA_PUBLIC_BASE_URL = os.getenv(
        "MEDIA_PUBLIC_BASE_URL", "http://localhost:5000/media"
    ).rstrip("/")
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
    GOOGLE_DRIVE_PRODUCT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_PRODUCT_FOLDER_ID", "")
    GOOGLE_DRIVE_GALLERY_FOLDER_ID = os.getenv("GOOGLE_DRIVE_GALLERY_FOLDER_ID", "")
    MEDIA_TOKEN_ENCRYPTION_KEY = os.getenv("MEDIA_TOKEN_ENCRYPTION_KEY", "")
    ORDER_RESERVATION_MINUTES = int(os.getenv("ORDER_RESERVATION_MINUTES", "30"))
    SHIPPING_METHOD = os.getenv("SHIPPING_METHOD", "manual").strip()
    SHIPPING_LABEL = os.getenv("SHIPPING_LABEL", "Entrega padrão").strip()
    SHIPPING_FLAT_RATE_CENTS = int(os.getenv("SHIPPING_FLAT_RATE_CENTS", "0"))
    SHIPPING_FREE_THRESHOLD_CENTS = int(os.getenv("SHIPPING_FREE_THRESHOLD_CENTS", "0"))
    SHIPPING_ESTIMATED_DAYS = int(os.getenv("SHIPPING_ESTIMATED_DAYS", "0")) or None
    PASSWORD_RESET_MINUTES = int(os.getenv("PASSWORD_RESET_MINUTES", "30"))
    EMAIL_DELIVERY_MODE = os.getenv("EMAIL_DELIVERY_MODE", "log").strip().lower()
    EMAIL_SANDBOX_RECIPIENT = os.getenv("EMAIL_SANDBOX_RECIPIENT", "").strip().lower()
    EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "").strip().lower()
    EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Movimento 7").strip()
    EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", "").strip().lower()
    EMAIL_CONTACT_RECIPIENT = os.getenv("EMAIL_CONTACT_RECIPIENT", "").strip().lower()
    ERROR_REPORTING_DSN = os.getenv("ERROR_REPORTING_DSN", "").strip()
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
    # O Google exibe senhas de app em quatro grupos; os espaços são apenas visuais.
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
    SMTP_USE_TLS = env_bool("SMTP_USE_TLS", True)

    @classmethod
    def validate(cls) -> None:
        if cls.EMAIL_DELIVERY_MODE not in {"log", "sandbox", "live"}:
            raise RuntimeError("EMAIL_DELIVERY_MODE deve ser log, sandbox ou live")
        if cls.SHIPPING_FLAT_RATE_CENTS < 0 or cls.SHIPPING_FREE_THRESHOLD_CENTS < 0:
            raise RuntimeError("As tarifas de frete não podem ser negativas")
        if cls.APP_ENV != "production":
            return
        missing: list[str] = []
        for name in ("SECRET_KEY", "DATABASE_URL", "PUBLIC_BASE_URL"):
            value = os.getenv(name, "")
            if not value or "change-me" in value:
                missing.append(name)
        if not cls.SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
            missing.append("DATABASE_URL_POSTGRESQL")
        if cls.MEDIA_PROVIDER not in {"local", "google_drive"}:
            missing.append("MEDIA_PROVIDER_VALID")
        if cls.MEDIA_PROVIDER == "google_drive":
            for name in (
                "MEDIA_TOKEN_ENCRYPTION_KEY",
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_DRIVE_PRODUCT_FOLDER_ID",
                "GOOGLE_DRIVE_GALLERY_FOLDER_ID",
            ):
                if not os.getenv(name, "").strip():
                    missing.append(name)
        if cls.EMAIL_DELIVERY_MODE == "live":
            for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM_ADDRESS"):
                if not os.getenv(name, "").strip():
                    missing.append(name)
        if missing:
            raise RuntimeError("Configuração de produção incompleta: " + ", ".join(missing))


class TestConfig(Config):
    TESTING = True
    APP_ENV = "test"
    SECRET_KEY = "test-only-secret-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"
    SESSION_COOKIE_SECURE = False
