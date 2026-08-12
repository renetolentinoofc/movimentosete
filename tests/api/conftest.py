import pytest

from movimento7 import create_app
from movimento7.config import TestConfig
from movimento7.extensions import db


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
