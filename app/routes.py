"""Rotas públicas, inscrição e painel administrativo."""

from __future__ import annotations

import csv
import hmac
import io
import os
from functools import wraps
from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from google_auth_oauthlib.flow import Flow

from . import db
from .google_drive import DRIVE_SCOPES
from .forms import AdminLoginForm, RegistrationForm
from .models import Registration, Sponsor

bp = Blueprint("main", __name__)


def admin_required(view):
    """Protege o painel com uma sessão simples e senha vinda do ambiente."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Faça login para acessar o painel.", "warning")
            return redirect(url_for("main.admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@bp.get("/")
def home():
    sponsors = (
        Sponsor.query.filter_by(active=True).order_by(Sponsor.display_order).all()
    )
    return render_template("index.html", sponsors=sponsors)


@bp.route("/inscricao", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        registration = Registration(
            full_name=form.full_name.data.strip(),
            social_name=(form.social_name.data or "").strip() or None,
            email=form.email.data.strip().lower(),
            phone=form.phone.data.strip(),
            neighborhood=form.neighborhood.data.strip(),
            city=form.city.data.strip(),
            participation_type=form.participation_type.data,
            experience=form.experience.data.strip(),
            instagram=(form.instagram.data or "").strip() or None,
            portfolio_url=(form.portfolio_url.data or "").strip() or None,
            equipment_needed=(form.equipment_needed.data or "").strip() or None,
            accessibility_needs=(form.accessibility_needs.data or "").strip() or None,
            availability=form.availability.data,
            lgpd_consent=bool(form.lgpd_consent.data),
        )
        db.session.add(registration)
        db.session.commit()
        return redirect(url_for("main.registration_success"))
    return render_template("register.html", form=form)


@bp.get("/inscricao/recebida")
def registration_success():
    return render_template("success.html")


@bp.get("/privacidade")
def privacy():
    return render_template("privacy.html")


@bp.get("/saude")
def health():
    return {"status": "ok", "service": "movimento7"}, 200


@bp.route("/admin/entrar", methods=["GET", "POST"])
def admin_login():
    form = AdminLoginForm()
    if form.validate_on_submit():
        expected = current_app.config["ADMIN_PASSWORD"]
        if hmac.compare_digest(form.password.data, expected):
            session.clear()
            session["is_admin"] = True
            return redirect(request.args.get("next") or url_for("main.admin_dashboard"))
        flash("Senha incorreta.", "danger")
    return render_template("admin_login.html", form=form)


@bp.post("/admin/sair")
@admin_required
def admin_logout():
    session.clear()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("main.home"))


@bp.get("/admin")
@admin_required
def admin_dashboard():
    status = request.args.get("status", "").strip()
    query = Registration.query.order_by(Registration.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    registrations = query.all()
    totals = {
        "all": Registration.query.count(),
        "received": Registration.query.filter_by(status="recebida").count(),
        "approved": Registration.query.filter_by(status="aprovada").count(),
    }
    return render_template(
        "admin_dashboard.html",
        registrations=registrations,
        totals=totals,
        current_status=status,
    )


@bp.post("/admin/inscricoes/<int:registration_id>/status")
@admin_required
def update_status(registration_id: int):
    registration = db.get_or_404(Registration, registration_id)
    allowed = {"recebida", "em_analise", "aprovada", "lista_espera", "recusada"}
    new_status = request.form.get("status", "")
    if new_status not in allowed:
        flash("Status inválido.", "danger")
    else:
        registration.status = new_status
        db.session.commit()
        flash("Status atualizado.", "success")
    return redirect(url_for("main.admin_dashboard"))


@bp.get("/admin/inscricoes.csv")
@admin_required
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "Data",
            "Nome",
            "Nome social",
            "Email",
            "WhatsApp",
            "Bairro",
            "Cidade",
            "Participação",
            "Disponibilidade",
            "Instagram",
            "Portfólio",
            "Experiência",
            "Equipamento",
            "Acessibilidade",
            "Status",
        ]
    )
    for item in Registration.query.order_by(Registration.created_at).all():
        writer.writerow(
            [
                item.id,
                item.created_at.isoformat(),
                item.full_name,
                item.social_name or "",
                item.email,
                item.phone,
                item.neighborhood,
                item.city,
                item.participation_type,
                item.availability,
                item.instagram or "",
                item.portfolio_url or "",
                item.experience,
                item.equipment_needed or "",
                item.accessibility_needs or "",
                item.status,
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=inscricoes_movimento7.csv"
        },
    )


def _google_oauth_client_config() -> dict:
    """Monta a configuração OAuth sem gravar segredos no código."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")

    if missing:
        raise RuntimeError("Variáveis do Google ausentes: " + ", ".join(missing))

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _google_redirect_uri() -> str:
    """Retorna o callback exato usado no Google Cloud."""
    scheme = "http" if current_app.debug else "https"
    return url_for("main.google_callback", _external=True, _scheme=scheme)


@bp.get("/admin/google/autorizar")
@admin_required
def google_authorize():
    """Inicia a autorização da conta Google usada pelo Movimento 7."""
    try:
        flow = Flow.from_client_config(
            _google_oauth_client_config(),
            scopes=DRIVE_SCOPES,
            state=expected_state,
            redirect_uri=_google_redirect_uri(),
            code_verifier=code_verifier,
        )
    except RuntimeError as exc:
        current_app.logger.error("Falha ao configurar OAuth: %s", exc)
        flash(str(exc), "danger")
        return redirect(url_for("main.admin_dashboard"))

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["google_oauth_state"] = state
    session["google_oauth_state"] = state
    session["google_code_verifier"] = flow.code_verifier

    return redirect(authorization_url)


@bp.get("/admin/google/callback")
@admin_required
def google_callback():
    """Recebe o retorno do Google e apresenta o refresh token uma única vez."""
    expected_state = session.get("google_oauth_state")
    code_verifier = session.get("google_code_verifier")
    returned_state = request.args.get("state", "")

    if (
        not expected_state
        or not hmac.compare_digest(expected_state, returned_state)
        or not code_verifier
    ):
        session.pop("google_oauth_state", None)
        flash("A autorização expirou ou o estado OAuth é inválido.", "danger")
        return redirect(url_for("main.admin_dashboard"))

    if request.args.get("error"):
        session.pop("google_oauth_state", None)
        flash("A autorização do Google foi cancelada.", "warning")
        return redirect(url_for("main.admin_dashboard"))

    try:
        flow = Flow.from_client_config(
            _google_oauth_client_config(),
            scopes=DRIVE_SCOPES,
            state=expected_state,
            redirect_uri=_google_redirect_uri(),
        )
        callback_url = url_for(
            "main.google_callback",
            _external=True,
            _scheme="https",
        )

        if request.query_string:
            callback_url = f"{callback_url}?" f"{request.query_string.decode('utf-8')}"

        flow.fetch_token(
            authorization_response=callback_url,
        )
    except Exception:
        current_app.logger.exception("Falha ao concluir o OAuth do Google")
        session.pop("google_oauth_state", None)
        flash("Não foi possível concluir a autorização do Google.", "danger")
        return redirect(url_for("main.admin_dashboard"))

    session.pop("google_oauth_state", None)
    session.pop("google_oauth_state", None)
    session.pop("google_code_verifier", None)
    refresh_token = flow.credentials.refresh_token

    if not refresh_token:
        flash(
            "O Google não retornou um refresh token. Revogue o acesso anterior "
            "e tente autorizar novamente.",
            "danger",
        )
        return redirect(url_for("main.admin_dashboard"))

    response = Response(
        render_template("google_oauth_result.html", refresh_token=refresh_token)
    )
    # O token não deve ser armazenado pelo navegador, proxy ou CDN.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response
