from datetime import UTC, datetime

from flask import Blueprint, current_app
from sqlalchemy import text

from ..extensions import db
from ..http import failure, success
from ..security import require_permission
from ..services.email_delivery import email_configuration

bp = Blueprint("health", __name__)


@bp.get("/health/live")
def live():
    return success({"status": "ok", "version": current_app.config["APP_VERSION"]})


@bp.get("/admin/health/ready")
@require_permission("system.read")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        return failure("database_unavailable", "Banco indisponível.", status=503)
    return success(
        {
            "status": "ready",
            "database": "available",
            "media": current_app.config["MEDIA_PROVIDER"],
            "checked_at": datetime.now(UTC).isoformat(),
        }
    )


@bp.get("/admin/readiness")
@require_permission("system.read")
def readiness():
    checks: list[dict[str, object]] = []
    try:
        db.session.execute(text("SELECT 1"))
        checks.append({"key": "database", "status": "pass", "label": "Banco acessível"})
    except Exception:
        checks.append({"key": "database", "status": "block", "label": "Banco indisponível"})

    production = current_app.config["APP_ENV"] == "production"
    secure_secret = current_app.config["SECRET_KEY"] != "local-development-only-change-me"
    checks.append({
        "key": "secrets",
        "status": "pass" if secure_secret or not production else "block",
        "label": (
            "Segredo de sessão configurado"
            if secure_secret or not production
            else "Segredo de sessão pendente"
        ),
    })
    checks.append({
        "key": "email",
        "status": "pass" if email_configuration()["configured"] else "warn",
        "label": (
            "E-mail configurado"
            if email_configuration()["configured"]
            else "E-mail ainda não configurado"
        ),
    })
    checks.append({
        "key": "payments",
        "status": "pass" if current_app.config["PAYMENT_PROVIDER"] != "manual" else "warn",
        "label": (
            "Gateway de pagamento conectado"
            if current_app.config["PAYMENT_PROVIDER"] != "manual"
            else "Pagamento manual (sem aprovação automática)"
        ),
    })
    checks.append({
        "key": "auction",
        "status": "pass" if current_app.config["AUCTION_BIDDING_ENABLED"] else "warn",
        "label": (
            "Lances habilitados"
            if current_app.config["AUCTION_BIDDING_ENABLED"]
            else "Lances monetários desativados"
        ),
    })
    blocking = any(check["status"] == "block" for check in checks)
    return success({"status": "blocked" if blocking else "review", "checks": checks})
