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
    AUCTION_PAYMENT_GUARANTEE_ENABLED = env_bool("AUCTION_PAYMENT_GUARANTEE_ENABLED", False)
    AUCTION_TERMS_VERSION = os.getenv("AUCTION_TERMS_VERSION", "2026-08-draft").strip()
    PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "manual").strip().lower().replace("_", "")
    PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip()
    MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "").strip()
    MERCADOPAGO_API_BASE_URL = os.getenv(
        "MERCADOPAGO_API_BASE_URL", "https://api.mercadopago.com"
    ).strip().rstrip("/")
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
    SHIPPING_PROVIDER = os.getenv("SHIPPING_PROVIDER", "manual").strip().lower()
    SHIPPING_ALLOWED_STATES = os.getenv("SHIPPING_ALLOWED_STATES", "").strip()
    SHIPPING_PICKUP_ENABLED = env_bool("SHIPPING_PICKUP_ENABLED", False)
    SHIPPING_PICKUP_LABEL = os.getenv("SHIPPING_PICKUP_LABEL", "Retirada no local").strip()
    SHIPPING_ORIGIN_POSTAL_CODE = os.getenv("SHIPPING_ORIGIN_POSTAL_CODE", "").strip()
    MELHOR_ENVIO_ACCESS_TOKEN = os.getenv("MELHOR_ENVIO_ACCESS_TOKEN", "").strip()
    MELHOR_ENVIO_API_BASE_URL = os.getenv(
        "MELHOR_ENVIO_API_BASE_URL", "https://sandbox.melhorenvio.com.br/api/v2/me"
    ).strip().rstrip("/")
    MELHOR_ENVIO_USER_AGENT = os.getenv(
        "MELHOR_ENVIO_USER_AGENT", "Movimento 7 suporte@movimento7.com.br"
    ).strip()
    SHIPPING_DEFAULT_WEIGHT_KG = float(os.getenv("SHIPPING_DEFAULT_WEIGHT_KG", "0.3"))
    SHIPPING_DEFAULT_WIDTH_CM = int(os.getenv("SHIPPING_DEFAULT_WIDTH_CM", "20"))
    SHIPPING_DEFAULT_HEIGHT_CM = int(os.getenv("SHIPPING_DEFAULT_HEIGHT_CM", "10"))
    SHIPPING_DEFAULT_LENGTH_CM = int(os.getenv("SHIPPING_DEFAULT_LENGTH_CM", "30"))
    SHIPPING_LABEL = os.getenv("SHIPPING_LABEL", "Entrega padrão").strip()
    SHIPPING_FLAT_RATE_CENTS = int(os.getenv("SHIPPING_FLAT_RATE_CENTS", "0"))
    SHIPPING_FREE_THRESHOLD_CENTS = int(os.getenv("SHIPPING_FREE_THRESHOLD_CENTS", "0"))
    SHIPPING_ESTIMATED_DAYS = int(os.getenv("SHIPPING_ESTIMATED_DAYS", "0")) or None
    PASSWORD_RESET_MINUTES = int(os.getenv("PASSWORD_RESET_MINUTES", "30"))
    EMAIL_DELIVERY_MODE = os.getenv("EMAIL_DELIVERY_MODE", "log").strip().lower()
    if EMAIL_DELIVERY_MODE == "smtp":
        EMAIL_DELIVERY_MODE = "live"
    EMAIL_SANDBOX_RECIPIENT = os.getenv("EMAIL_SANDBOX_RECIPIENT", "").strip().lower()
    EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "").strip().lower()
    EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Movimento 7").strip()
    EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", "").strip().lower()
    EMAIL_CONTACT_RECIPIENT = os.getenv("EMAIL_CONTACT_RECIPIENT", "").strip().lower()
    ERROR_REPORTING_DSN = os.getenv("ERROR_REPORTING_DSN", "").strip()
    ERROR_REPORTING_TRACES_SAMPLE_RATE = float(
        os.getenv("ERROR_REPORTING_TRACES_SAMPLE_RATE", "0")
    )
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
    # O Google exibe senhas de app em quatro grupos; os espaços são apenas visuais.
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
    SMTP_USE_TLS = env_bool("SMTP_USE_TLS", True)

    @classmethod
    def validate(cls) -> None:
        if cls.PAYMENT_PROVIDER not in {"manual", "mercadopago"}:
            raise RuntimeError(
                "PAYMENT_PROVIDER aponta para um adaptador não instalado: "
                + cls.PAYMENT_PROVIDER
            )
        if cls.EMAIL_DELIVERY_MODE not in {"log", "sandbox", "live"}:
            raise RuntimeError("EMAIL_DELIVERY_MODE deve ser log, sandbox ou smtp/live")
        if cls.SHIPPING_FLAT_RATE_CENTS < 0 or cls.SHIPPING_FREE_THRESHOLD_CENTS < 0:
            raise RuntimeError("As tarifas de frete não podem ser negativas")
        if cls.SHIPPING_PROVIDER not in {"manual", "melhor_envio"}:
            raise RuntimeError("SHIPPING_PROVIDER deve ser manual ou melhor_envio")
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
        if cls.EMAIL_DELIVERY_MODE in {"smtp", "live"}:
            for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM_ADDRESS"):
                if not os.getenv(name, "").strip():
                    missing.append(name)
        if cls.PAYMENT_PROVIDER != "manual" and not cls.PAYMENT_WEBHOOK_SECRET:
            missing.append("PAYMENT_WEBHOOK_SECRET")
        if cls.PAYMENT_PROVIDER == "mercadopago" and not cls.MERCADOPAGO_ACCESS_TOKEN:
            missing.append("MERCADOPAGO_ACCESS_TOKEN")
        if cls.SHIPPING_PROVIDER == "melhor_envio":
            for name in ("MELHOR_ENVIO_ACCESS_TOKEN", "SHIPPING_ORIGIN_POSTAL_CODE"):
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
