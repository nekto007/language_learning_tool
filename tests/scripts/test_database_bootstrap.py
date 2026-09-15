"""Content tools must use the database registered with their Flask app."""

import importlib

import pytest
from flask import Flask

import app as app_package
from app.utils.db import db


@pytest.mark.parametrize(
    ("module_name", "helper_name"),
    [
        ("audit_immersion_data", "_try_get_db_session"),
        ("report_immersion_gaps", "_try_get_db_session"),
        ("export_vocabulary_priority", "_try_get_db"),
        ("report_vocabulary_enrichment", "_try_get_db"),
    ],
)
def test_bootstrap_returns_registered_database(monkeypatch, module_name, helper_name):
    tool = importlib.import_module(f"scripts.{module_name}")
    flask_app = Flask(__name__)
    # Creating the engine does not open a database connection.
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = (
        "postgresql://test_user:test_password@localhost/bootstrap_test"
    )
    db.init_app(flask_app)
    monkeypatch.setattr(app_package, "create_app", lambda: flask_app)

    created_app, tool_db = getattr(tool, helper_name)()

    assert created_app is flask_app
    assert tool_db is db
    with created_app.app_context():
        assert tool_db.engine is db.engine
