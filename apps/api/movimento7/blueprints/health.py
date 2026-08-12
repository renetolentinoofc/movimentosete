from datetime import UTC, datetime

from flask import Blueprint, current_app
from sqlalchemy import text

from ..extensions import db
from ..http import failure, success
from ..security import require_permission

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
