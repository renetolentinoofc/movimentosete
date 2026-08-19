import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, current_app, g, request
from sqlalchemy import func, select, update
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..http import failure, success
from ..models import AdminPasswordReset, AdminSession, AdminUser, LoginAttempt
from ..security import (
    audit,
    client_fingerprint,
    issue_token,
    permission_set,
    rate_limited,
    sha256,
)
from ..services.communications import dispatch_email
from ..services.email_delivery import valid_email
from ..services.email_templates import admin_password_reset
from ..validation import aware_utc

bp = Blueprint("auth", __name__)


def subject_hash(email: str) -> str:
    return hashlib.sha256(f"{email}:{client_fingerprint()}".encode()).hexdigest()


@bp.post("/admin/auth/password-reset/request")
def request_password_reset():
    if rate_limited("admin-password-reset-request", 5, 3600):
        db.session.rollback()
        return failure(
            "rate_limited", "Muitas solicitações. Tente novamente mais tarde.", status=429
        )

    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    generic_response = {
        "accepted": True,
        "message": "Se a conta existir, enviaremos as instruções de recuperação.",
    }
    if not valid_email(email):
        db.session.commit()
        return success(generic_response, status=202)

    user = db.session.scalar(select(AdminUser).where(AdminUser.email == email))
    if not user or not user.active or user.deleted_at:
        db.session.commit()
        return success(generic_response, status=202)

    now = datetime.now(UTC)
    previous = db.session.scalars(
        select(AdminPasswordReset).where(
            AdminPasswordReset.user_id == user.id,
            AdminPasswordReset.used_at.is_(None),
        )
    ).all()
    for item in previous:
        item.used_at = now

    raw_token = issue_token()
    expires_minutes = int(current_app.config["PASSWORD_RESET_MINUTES"])
    reset = AdminPasswordReset(
        user_id=user.id,
        token_hash=sha256(raw_token),
        expires_at=now + timedelta(minutes=expires_minutes),
        requested_at=now,
        ip_hash=client_fingerprint(),
    )
    db.session.add(reset)
    db.session.flush()
    reset_url = (
        f"{current_app.config['PUBLIC_BASE_URL']}/painel/redefinir-senha?"
        f"{urlencode({'token': raw_token})}"
    )
    dispatch_email(
        recipient=user.email,
        template=admin_password_reset(
            name=user.name,
            reset_url=reset_url,
            expires_minutes=expires_minutes,
        ),
        idempotency_key=f"password-reset:{reset.id}",
    )
    audit(
        "auth.password_reset_requested",
        "admin_user",
        "Recuperação de senha administrativa solicitada",
        str(user.id),
    )
    db.session.commit()
    return success(generic_response, status=202)


@bp.post("/admin/auth/password-reset/confirm")
def confirm_password_reset():
    if rate_limited("admin-password-reset-confirm", 10, 3600):
        db.session.rollback()
        return failure(
            "rate_limited", "Muitas tentativas. Solicite um novo link.", status=429
        )

    body = request.get_json(silent=True) or {}
    raw_token = str(body.get("token", "")).strip()
    new_password = str(body.get("new_password", ""))
    confirmation = str(body.get("password_confirmation", ""))
    reset = (
        db.session.scalar(
            select(AdminPasswordReset).where(AdminPasswordReset.token_hash == sha256(raw_token))
        )
        if raw_token
        else None
    )
    now = datetime.now(UTC)
    if (
        not reset
        or reset.used_at
        or aware_utc(reset.expires_at) <= now
        or not reset.user.active
        or reset.user.deleted_at
    ):
        db.session.commit()
        return failure(
            "reset_token_invalid",
            "Este link é inválido ou expirou. Solicite uma nova recuperação.",
            status=422,
        )
    fields: dict[str, list[str]] = {}
    if len(new_password) < 12:
        fields["new_password"] = ["A senha precisa ter 12 ou mais caracteres."]
    elif check_password_hash(reset.user.password_hash, new_password):
        fields["new_password"] = ["Escolha uma senha diferente da atual."]
    if confirmation != new_password:
        fields["password_confirmation"] = ["As senhas não conferem."]
    if fields:
        db.session.commit()
        return failure(
            "weak_password", "Revise a nova senha.", status=422, fields=fields
        )

    reset.user.password_hash = generate_password_hash(new_password)
    reset.user.must_change_password = False
    reset.user.session_version += 1
    unused_tokens = db.session.scalars(
        select(AdminPasswordReset).where(
            AdminPasswordReset.user_id == reset.user_id,
            AdminPasswordReset.used_at.is_(None),
        )
    ).all()
    for item in unused_tokens:
        item.used_at = now
    db.session.execute(
        update(AdminSession)
        .where(AdminSession.user_id == reset.user_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    audit(
        "auth.password_reset_completed",
        "admin_user",
        "Senha administrativa redefinida por link de uso único",
        str(reset.user_id),
    )
    db.session.commit()
    response, status = success({"changed": True, "reauthentication_required": True})
    response.delete_cookie("m7_session", path="/")
    return response, status


@bp.post("/admin/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    subject = subject_hash(email)
    since = datetime.now(UTC) - timedelta(minutes=15)
    failures = db.session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.subject_hash == subject,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
    )
    if int(failures or 0) >= 5:
        audit("auth.locked", "admin_user", "Tentativas de acesso temporariamente limitadas")
        db.session.commit()
        return failure(
            "login_limited", "Não foi possível entrar. Tente novamente mais tarde.", status=429
        )
    user = db.session.scalar(select(AdminUser).where(AdminUser.email == email))
    valid = bool(
        user
        and user.active
        and not user.deleted_at
        and check_password_hash(user.password_hash, password)
    )
    db.session.add(LoginAttempt(subject_hash=subject, success=valid, created_at=datetime.now(UTC)))
    if not valid:
        audit("auth.failed", "admin_user", "Falha de autenticação administrativa")
        db.session.commit()
        return failure("invalid_credentials", "E-mail ou senha inválidos.", status=401)
    raw_token = issue_token()
    raw_csrf = issue_token()
    session = AdminSession(
        user_id=user.id,
        token_hash=sha256(raw_token),
        csrf_token_hash=sha256(raw_csrf),
        user_session_version=user.session_version,
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        last_seen_at=datetime.now(UTC),
        ip_hash=client_fingerprint(),
        user_agent=(request.user_agent.string or "")[:255],
    )
    user.last_login_at = datetime.now(UTC)
    db.session.add(session)
    g.current_user = user
    audit("auth.login", "admin_user", "Acesso administrativo iniciado", str(user.id))
    db.session.commit()
    response, status = success(
        {
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "permissions": sorted(permission_set(user)),
                "must_change_password": user.must_change_password,
            },
            "csrf_token": raw_csrf,
        }
    )
    response.set_cookie(
        "m7_session",
        raw_token,
        httponly=True,
        secure=current_app.config["SESSION_COOKIE_SECURE"],
        samesite="Lax",
        max_age=8 * 60 * 60,
        path="/",
    )
    return response, status


@bp.get("/admin/auth/session")
def session_info():
    if not g.current_user:
        return failure("authentication_required", "Autenticação necessária.", status=401)
    raw_csrf = issue_token()
    g.admin_session.csrf_token_hash = sha256(raw_csrf)
    g.admin_session.last_seen_at = datetime.now(UTC)
    db.session.commit()
    return success(
        {
            "user": {
                "id": str(g.current_user.id),
                "name": g.current_user.name,
                "email": g.current_user.email,
                "permissions": sorted(permission_set(g.current_user)),
                "must_change_password": g.current_user.must_change_password,
            },
            "csrf_token": raw_csrf,
        }
    )


@bp.post("/admin/auth/logout")
def logout():
    if g.admin_session:
        g.admin_session.revoked_at = datetime.now(UTC)
        audit(
            "auth.logout",
            "admin_session",
            "Sessão administrativa encerrada",
            str(g.admin_session.id),
        )
        db.session.commit()
    response, status = success({"logged_out": True})
    response.delete_cookie("m7_session", path="/")
    return response, status


@bp.post("/admin/auth/change-password")
def change_password():
    if not g.current_user:
        return failure("authentication_required", "Autenticação necessária.", status=401)
    body = request.get_json(silent=True) or {}
    current = str(body.get("current_password", ""))
    new = str(body.get("new_password", ""))
    if not check_password_hash(g.current_user.password_hash, current):
        return failure("invalid_password", "A senha atual não confere.", status=422)
    if len(new) < 12 or new == current:
        return failure(
            "weak_password",
            "Use uma nova senha com pelo menos 12 caracteres.",
            status=422,
            fields={"new_password": ["A senha precisa ter 12 ou mais caracteres."]},
        )
    g.current_user.password_hash = generate_password_hash(new)
    g.current_user.must_change_password = False
    g.current_user.session_version += 1
    if g.admin_session:
        g.admin_session.revoked_at = datetime.now(UTC)
    audit(
        "auth.password_changed",
        "admin_user",
        "Senha administrativa alterada",
        str(g.current_user.id),
    )
    db.session.commit()
    response, status = success({"changed": True, "reauthentication_required": True})
    response.delete_cookie("m7_session", path="/")
    return response, status
