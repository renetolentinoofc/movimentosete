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
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
    MEDIA_TOKEN_ENCRYPTION_KEY = os.getenv("MEDIA_TOKEN_ENCRYPTION_KEY", "")
    ORDER_RESERVATION_MINUTES = int(os.getenv("ORDER_RESERVATION_MINUTES", "30"))

    @classmethod
    def validate(cls) -> None:
        if cls.APP_ENV != "production":
            return
        missing: list[str] = []
        for name in ("SECRET_KEY", "DATABASE_URL", "PUBLIC_BASE_URL"):
            value = os.getenv(name, "")
            if not value or "change-me" in value:
                missing.append(name)
        if not cls.SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
            missing.append("DATABASE_URL_POSTGRESQL")
        if missing:
            raise RuntimeError("Configuração de produção incompleta: " + ", ".join(missing))


class TestConfig(Config):
    TESTING = True
    APP_ENV = "test"
    SECRET_KEY = "test-only-secret-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"
    SESSION_COOKIE_SECURE = False
