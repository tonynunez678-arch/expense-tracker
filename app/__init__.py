"""Application factory: creates and configures the Flask app."""

import os

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()
csrf = CSRFProtect()


def _database_url(app):
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "sqlite:///" + os.path.join(app.instance_path, "expenses.db")
    # Hosts like Render hand out "postgres://..." or "postgresql://..." URLs.
    # Tell SQLAlchemy to use the psycopg (v3) driver for them.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=_database_url(app),
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,  # 1 MB upload limit for CSV import
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    from . import models  # noqa: F401  (registers the models with SQLAlchemy)
    from .auth import bp as auth_bp
    from .expenses import bp as expenses_bp
    from .money import format_cents

    app.register_blueprint(auth_bp)
    app.register_blueprint(expenses_bp)
    app.jinja_env.filters["money"] = format_cents

    with app.app_context():
        db.create_all()

    return app
