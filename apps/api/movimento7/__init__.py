import json
import logging
import secrets
import sys
from pathlib import Path

import click
from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from .blueprints import ALL_BLUEPRINTS
from .config import Config
from .extensions import cors, db, migrate
from .http import failure
from .security import load_session, verify_csrf
from .seeds import seed_all


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "request_id": getattr(record, "request_id", None),
            },
            ensure_ascii=False,
        )


def configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)


def create_app(config: type[Config] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config or Config)
    (config or Config).validate()
    configure_logging(app)
    db.init_app(app)
    migrate.init_app(app, db, directory=str(Path(__file__).resolve().parents[3] / "migrations"))
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
        allow_headers=("Content-Type", "X-CSRF-Token", "X-Upload-Token", "Idempotency-Key"),
    )

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/api/v1")

    @app.before_request
    def request_context():
        g.request_id = request.headers.get("X-Request-ID", "")[:64] or secrets.token_hex(16)
        load_session()
        return verify_csrf()

    @app.after_request
    def security_headers(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.path.startswith("/api/v1/admin") else "no-cache"
        )
        if app.config["APP_ENV"] == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        mapping = {
            400: "bad_request",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
            429: "rate_limited",
        }
        return failure(
            mapping.get(error.code or 500, "http_error"),
            error.description,
            status=error.code or 500,
        )

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        app.logger.exception("Unhandled request error", extra={"request_id": g.get("request_id")})
        db.session.rollback()
        return failure("internal_error", "Não foi possível concluir a operação.", status=500)

    @app.cli.command("reconcile-gallery")
    @click.option("--limit", default=500, show_default=True, type=click.IntRange(1, 500))
    def reconcile_gallery_command(limit: int) -> None:
        """Verifica mídias da galeria e registra pendências de reconciliação."""
        from .services.media import reconcile_gallery_media

        click.echo(json.dumps(reconcile_gallery_media(limit), ensure_ascii=False))

    @app.cli.command("expire-inventory-reservations")
    @click.option("--limit", default=500, show_default=True, type=click.IntRange(1, 5000))
    def expire_inventory_reservations_command(limit: int) -> None:
        """Libera reservas de estoque vencidas e expira pedidos não pagos."""
        from .services.inventory import expire_inventory_reservations

        click.echo(json.dumps(expire_inventory_reservations(limit), ensure_ascii=False))

    @app.cli.command("seed")
    def seed_command():
        """Aplica dados iniciais idempotentes."""
        seed_all()
        click.echo("Seeds aplicados com sucesso.")

    return app
