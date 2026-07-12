"""Modelos persistidos no PostgreSQL do Render ou no SQLite local."""

from __future__ import annotations
from datetime import datetime, timezone
from . import db


class Registration(db.Model):
    __tablename__ = "registrations"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(140), nullable=False, index=True)
    social_name = db.Column(db.String(140))
    email = db.Column(db.String(180), nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False)
    neighborhood = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False, default="Belo Horizonte")
    participation_type = db.Column(db.String(50), nullable=False, index=True)
    experience = db.Column(db.Text, nullable=False)
    instagram = db.Column(db.String(120))
    portfolio_url = db.Column(db.String(300))
    equipment_needed = db.Column(db.Text)
    accessibility_needs = db.Column(db.Text)
    availability = db.Column(db.String(80), nullable=False)
    lgpd_consent = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(30), nullable=False, default="recebida", index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Sponsor(db.Model):
    __tablename__ = "sponsors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    logo_filename = db.Column(db.String(180), nullable=False)
    description = db.Column(db.String(240))
    website_url = db.Column(db.String(300))
    display_order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
