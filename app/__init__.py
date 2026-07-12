"""Fábrica da aplicação Movimento 7.

A função ``create_app`` permite usar o mesmo código no desenvolvimento local,
no Gunicorn e no Render sem duplicar configuração.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

# Extensões são criadas sem app para facilitar testes e manutenção.
db = SQLAlchemy()
csrf = CSRFProtect()


def create_app() -> Flask:
    """Cria e configura uma instância da aplicação Flask."""
    load_dotenv()

    # Aceita escopos adicionais já concedidos pela conta sem interromper o OAuth.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

    app = Flask(__name__, instance_relative_config=True)
    # O Render executa a aplicação atrás de um proxy HTTPS.
    # Isso permite que o Flask reconheça corretamente o domínio e o protocolo público.
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    database_url = os.getenv("DATABASE_URL", "").strip()

    # Alguns provedores antigos ainda entregam URLs iniciadas por postgres://.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # Em desenvolvimento local, usa SQLite quando DATABASE_URL estiver vazia.
    if not database_url:
        database_url = f"sqlite:///{Path(app.instance_path) / 'movimento7.db'}"

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-me"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "pool_recycle": 280,
            "pool_size": 3,
            "max_overflow": 2,
            "pool_timeout": 30,
        },
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", "admin-change-me"),
        # Limite inicial para uploads futuros da galeria: 8 MB.
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Em produção, cookies de sessão só trafegam por HTTPS.
        SESSION_COOKIE_SECURE=os.getenv("FLASK_DEBUG", "0") != "1",
    )

    db.init_app(app)
    csrf.init_app(app)

    # As rotas ficam concentradas em app/routes.py e são registradas aqui.
    from .routes import bp

    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()
        _seed_sponsors()

    return app


def _seed_sponsors() -> None:
    """Inclui os patrocinadores iniciais sem duplicar registros."""
    from .models import Sponsor

    initial = [
        (
            "DF Refrigeração",
            "logo_df_refrigeracao.png",
            "Refrigeração e climatização",
        ),
        (
            "Açaí do Boy",
            "logo_acai_do_boy.png",
            "Alimentação e energia para o evento",
        ),
        ("Baianão Carnes", "logo_baianao_carnes.png", "Certeza de qualidade"),
        (
            "Garagem dos Antigos",
            "garagem_dos_antigos.png",
            "Cultura automotiva e comunidade",
        ),
    ]

    changed = False
    for order, (name, logo, description) in enumerate(initial, start=1):
        if not Sponsor.query.filter_by(name=name).first():
            db.session.add(
                Sponsor(
                    name=name,
                    logo_filename=logo,
                    description=description,
                    display_order=order,
                )
            )
            changed = True

    if changed:
        db.session.commit()
