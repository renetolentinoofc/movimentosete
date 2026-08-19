from sqlalchemy import func, select
from werkzeug.security import check_password_hash

from movimento7.extensions import db
from movimento7.models import AdminUser
from movimento7.seeds import seed_all


def test_seed_creates_initial_admin_once(app, monkeypatch):
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "admin@movimento7.com")
    monkeypatch.setenv("INITIAL_ADMIN_NAME", "Administrador Movimento 7")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "senha-inicial-teste-segura")

    with app.app_context():
        seed_all()
        seed_all()

        count = db.session.scalar(select(func.count()).select_from(AdminUser))
        admin = db.session.scalar(
            select(AdminUser).where(AdminUser.email == "admin@movimento7.com")
        )

        assert count == 1
        assert admin is not None
        assert admin.must_change_password is True
        assert check_password_hash(admin.password_hash, "senha-inicial-teste-segura")
