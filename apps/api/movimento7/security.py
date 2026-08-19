import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, TypeVar, cast

from flask import current_app, g, request
from sqlalchemy import func, select

from .extensions import db
from .http import failure
from .models import AdminSession, AdminUser, AuditLog, RateLimitEvent
from .validation import aware_utc

F = TypeVar("F", bound=Callable[..., Any])


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def client_fingerprint() -> str:
    address = request.remote_addr or "unknown"
    return sha256(address + current_app.config["SECRET_KEY"][:16])


def issue_token() -> str:
    return secrets.token_urlsafe(32)


def audit(action: str, resource_type: str, summary: str, resource_id: str | None = None) -> None:
    db.session.add(
        AuditLog(
            actor_user_id=getattr(g, "current_user", None).id
            if getattr(g, "current_user", None)
            else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            summary=summary[:500],
            request_id=g.request_id,
            ip_hash=client_fingerprint(),
            metadata_json="{}",
            created_at=datetime.now(UTC),
        )
    )


def load_session() -> None:
    g.current_user = None
    g.admin_session = None
    raw = request.cookies.get("m7_session")
    if not raw:
        return
    session = db.session.scalar(select(AdminSession).where(AdminSession.token_hash == sha256(raw)))
    now = datetime.now(UTC)
    if not session or session.revoked_at or aware_utc(session.expires_at) <= now:
        return
    user = db.session.get(AdminUser, session.user_id)
    if (
        not user
        or not user.active
        or user.deleted_at
        or user.session_version != session.user_session_version
    ):
        return
    g.current_user = user
    g.admin_session = session


def permission_set(user: AdminUser) -> set[str]:
    return {permission.slug for role in user.roles for permission in role.permissions}


def require_permission(permission: str) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not g.current_user:
                return failure("authentication_required", "Autenticação necessária.", status=401)
            if g.current_user.must_change_password:
                return failure(
                    "password_change_required",
                    "Troque a senha inicial antes de continuar.",
                    status=403,
                )
            if permission not in permission_set(g.current_user):
                return failure(
                    "permission_denied", "Você não possui permissão para esta ação.", status=403
                )
            return fn(*args, **kwargs)

        return cast(F, wrapped)

    return decorator


def verify_csrf() -> tuple[Any, int] | None:
    public_admin_mutations = {
        "auth.login",
        "auth.request_password_reset",
        "auth.confirm_password_reset",
    }
    if (
        request.method in {"GET", "HEAD", "OPTIONS"}
        or not g.current_user
        or not request.path.startswith("/api/v1/admin/")
        or request.endpoint in public_admin_mutations
    ):
        return None
    supplied = request.headers.get("X-CSRF-Token", "")
    expected_hash = g.admin_session.csrf_token_hash if g.admin_session else None
    if (
        not supplied
        or not expected_hash
        or not hmac.compare_digest(sha256(supplied), expected_hash)
    ):
        return failure(
            "csrf_invalid", "A sessão de segurança expirou. Atualize a página.", status=403
        )
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") not in current_app.config["CORS_ORIGINS"]:
        return failure("origin_invalid", "Origem da requisição não autorizada.", status=403)
    return None


def rate_limited(scope: str, limit: int, window_seconds: int) -> bool:
    now = datetime.now(UTC)
    threshold = now - timedelta(seconds=window_seconds)
    bucket = sha256(f"{scope}:{client_fingerprint()}")
    count = db.session.scalar(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(RateLimitEvent.bucket_hash == bucket, RateLimitEvent.created_at >= threshold)
    )
    if int(count or 0) >= limit:
        return True
    db.session.add(RateLimitEvent(bucket_hash=bucket, created_at=now))
    return False
