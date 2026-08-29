"""Rotas públicas, inscrição, galeria e painel administrativo."""

from __future__ import annotations

import csv
import hmac
import io
import os
from functools import wraps
from urllib.parse import unquote, urlsplit

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from google_auth_oauthlib.flow import Flow

from . import db
from .forms import (
    AdminLoginForm,
    GalleryImageEditForm,
    GalleryImageForm,
    RegistrationForm,
)
from .google_drive import (
    DRIVE_SCOPES,
    delete_drive_image,
    download_drive_image,
    get_gallery_folder_info,
    google_drive_is_connected,
    save_refresh_token,
    upload_gallery_image,
)
from .models import GalleryImage, Registration, Sponsor

bp = Blueprint("main", __name__)


def _safe_next_path(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    if not candidate.startswith("/") or candidate.startswith("//") or "\\" in candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate


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
    sponsors = Sponsor.query.filter_by(active=True).order_by(Sponsor.display_order).all()
    gallery_images = (
        GalleryImage.query.filter_by(active=True)
        .order_by(GalleryImage.display_order.asc(), GalleryImage.created_at.desc())
        .all()
    )
    return render_template(
        "index.html",
        sponsors=sponsors,
        gallery_images=gallery_images,
    )


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
            next_path = _safe_next_path(request.args.get("next"))
            return redirect(next_path or url_for("main.admin_dashboard"))
        flash("Senha incorreta.", "danger")
    return render_template("admin_login.html", form=form)


@bp.post("/admin/sair")
@admin_required
def admin_logout():
    session.clear()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("main.home"))


@bp.get("/admin", strict_slashes=False)
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
        drive_connected=google_drive_is_connected(),
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
            "ID", "Data", "Nome", "Nome social", "Email", "WhatsApp", "Bairro",
            "Cidade", "Participação", "Disponibilidade", "Instagram", "Portfólio",
            "Experiência", "Equipamento", "Acessibilidade", "Status",
        ]
    )
    for item in Registration.query.order_by(Registration.created_at).all():
        writer.writerow(
            [
                item.id, item.created_at.isoformat(), item.full_name,
                item.social_name or "", item.email, item.phone, item.neighborhood,
                item.city, item.participation_type, item.availability,
                item.instagram or "", item.portfolio_url or "", item.experience,
                item.equipment_needed or "", item.accessibility_needs or "", item.status,
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=inscricoes_movimento7.csv"},
    )


# ---------------------------------------------------------------------------
# Google OAuth: o refresh token é salvo criptografado no PostgreSQL.
# Assim, não é necessário editar o Environment nem disparar outro deploy.
# ---------------------------------------------------------------------------

def _google_oauth_client_config() -> dict:
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
    scheme = "http" if current_app.debug else "https"
    return url_for("main.google_callback", _external=True, _scheme=scheme)


@bp.get("/admin/google/autorizar")
@admin_required
def google_authorize():
    try:
        flow = Flow.from_client_config(
            _google_oauth_client_config(),
            scopes=DRIVE_SCOPES,
            redirect_uri=_google_redirect_uri(),
            autogenerate_code_verifier=False,
        )
    except RuntimeError as exc:
        current_app.logger.error("Falha ao configurar OAuth: %s", exc)
        flash(str(exc), "danger")
        return redirect(url_for("main.gallery_admin"))

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    session["google_oauth_state"] = state
    return redirect(authorization_url)


@bp.get("/admin/google/callback")
@admin_required
def google_callback():
    expected_state = session.get("google_oauth_state")
    if not expected_state:
        flash("A sessão de autorização expirou. Tente novamente.", "danger")
        return redirect(url_for("main.gallery_admin"))

    flow = Flow.from_client_config(
        _google_oauth_client_config(),
        scopes=DRIVE_SCOPES,
        state=expected_state,
        redirect_uri=_google_redirect_uri(),
        autogenerate_code_verifier=False,
    )

    callback_url = url_for("main.google_callback", _external=True, _scheme="https")
    if request.query_string:
        callback_url = f"{callback_url}?{request.query_string.decode('utf-8')}"

    try:
        flow.fetch_token(authorization_response=callback_url)
        refresh_token = flow.credentials.refresh_token
        if not refresh_token:
            raise RuntimeError("O Google não retornou um refresh token.")
        save_refresh_token(refresh_token)
    except Exception:
        current_app.logger.exception("Falha ao concluir o OAuth do Google")
        flash("Não foi possível concluir a autorização do Google.", "danger")
        return redirect(url_for("main.gallery_admin"))
    finally:
        session.pop("google_oauth_state", None)

    flash("Google Drive conectado. Já é possível adicionar fotos.", "success")
    return redirect(url_for("main.gallery_admin"))


# ---------------------------------------------------------------------------
# Galeria administrativa
# ---------------------------------------------------------------------------

@bp.route("/admin/galeria", methods=["GET", "POST"])
@admin_required
def gallery_admin():
    form = GalleryImageForm()
    connected = google_drive_is_connected()

    if form.validate_on_submit():
        if not connected:
            flash("Conecte o Google Drive antes de enviar uma foto.", "warning")
            return redirect(url_for("main.gallery_admin"))

        try:
            current_app.logger.info(
                "Upload de galeria recebido: filename=%s content_length=%s",
                getattr(form.image.data, "filename", ""),
                request.content_length,
            )
            folder = get_gallery_folder_info()
            current_app.logger.info(
                "Pasta do Google Drive validada: id=%s nome=%s",
                folder.get("id"),
                folder.get("name"),
            )
            uploaded = upload_gallery_image(form.image.data, form.title.data)
            image = GalleryImage(
                title=form.title.data.strip(),
                description=(form.description.data or "").strip() or None,
                alt_text=form.alt_text.data.strip(),
                drive_file_id=uploaded["id"],
                mime_type=uploaded["mime_type"],
                display_order=form.display_order.data or 0,
                active=bool(form.active.data),
            )
            db.session.add(image)
            db.session.commit()
            flash("Foto adicionada à galeria.", "success")
            return redirect(url_for("main.gallery_admin"))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao enviar foto para o Google Drive")
            flash("Não foi possível enviar a foto. Consulte os logs do Render.", "danger")
    elif request.method == "POST":
        current_app.logger.warning(
            "Formulário da galeria inválido: %s",
            form.errors,
        )
        flash("Revise os campos indicados antes de enviar a foto.", "warning")

    images = GalleryImage.query.order_by(
        GalleryImage.display_order.asc(), GalleryImage.created_at.desc()
    ).all()
    return render_template(
        "admin_gallery.html",
        form=form,
        images=images,
        drive_connected=connected,
    )


@bp.route(
    "/admin/galeria/<int:image_id>/editar",
    methods=["GET", "POST"],
)
@admin_required
def gallery_edit(image_id: int):
    """Permite editar os metadados de uma foto sem reenviá-la ao Drive."""
    image = db.get_or_404(GalleryImage, image_id)
    form = GalleryImageEditForm(obj=image)

    if form.validate_on_submit():
        image.title = form.title.data.strip()
        image.description = (form.description.data or "").strip() or None
        image.display_order = form.display_order.data

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Falha ao editar dados da foto da galeria"
            )
            flash("Não foi possível salvar as alterações.", "danger")
        else:
            flash("Foto atualizada com sucesso.", "success")
            return redirect(url_for("main.gallery_admin"))

    return render_template(
        "admin_gallery_edit.html",
        form=form,
        image=image,
    )


@bp.post("/admin/galeria/<int:image_id>/alternar")
@admin_required
def gallery_toggle(image_id: int):
    image = db.get_or_404(GalleryImage, image_id)
    image.active = not image.active
    db.session.commit()
    flash("Visibilidade da foto atualizada.", "success")
    return redirect(url_for("main.gallery_admin"))


@bp.post("/admin/galeria/<int:image_id>/excluir")
@admin_required
def gallery_delete(image_id: int):
    image = db.get_or_404(GalleryImage, image_id)
    try:
        delete_drive_image(image.drive_file_id)
    except Exception:
        current_app.logger.exception("Falha ao excluir arquivo do Google Drive")
        flash("O arquivo não pôde ser excluído do Drive.", "danger")
        return redirect(url_for("main.gallery_admin"))

    db.session.delete(image)
    db.session.commit()
    flash("Foto excluída da galeria.", "success")
    return redirect(url_for("main.gallery_admin"))


@bp.get("/galeria/imagem/<int:image_id>")
def gallery_media(image_id: int):
    image = db.get_or_404(GalleryImage, image_id)
    if not image.active and not session.get("is_admin"):
        return Response(status=404)

    try:
        stream = download_drive_image(image.drive_file_id)
    except Exception:
        current_app.logger.exception("Falha ao carregar imagem da galeria")
        return Response(status=404)

    response = send_file(
        stream,
        mimetype=image.mime_type,
        download_name=f"galeria-{image.id}.webp",
        max_age=3600,
        conditional=True,
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response
