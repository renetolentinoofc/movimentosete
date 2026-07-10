"""Fábrica da aplicação Movimento 7.

A função create_app permite usar o mesmo código no desenvolvimento local,
no Gunicorn e no Render sem duplicar configuração.
"""
from __future__ import annotations

import os
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

# Extensões são criadas sem app para facilitar testes e manutenção.
db = SQLAlchemy()
csrf = CSRFProtect()


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    database_url = os.getenv("DATABASE_URL", "").strip()
    # Render já usa postgresql://, mas provedores antigos podem entregar postgres://.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if not database_url:
        database_url = f"sqlite:///{Path(app.instance_path) / 'movimento7.db'}"

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-me"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", "admin-change-me"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    db.init_app(app)
    csrf.init_app(app)

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
        ("DF Refrigeração", "logo_df_refrigeracao.png", "Refrigeração e climatização"),
        ("Açaí do Boy", "logo_acai_do_boy.png", "Alimentação e energia para o evento"),
        ("Baianão Carnes", "logo_baianao_carnes.png", "Certeza de qualidade"),
        ("Garagem dos Antigos", "garagem_dos_antigos.png", "Cultura automotiva e comunidade"),
    ]
    changed = False
    for order, (name, logo, description) in enumerate(initial, start=1):
        if not Sponsor.query.filter_by(name=name).first():
            db.session.add(Sponsor(name=name, logo_filename=logo, description=description, display_order=order))
            changed = True
    if changed:
        db.session.commit()
