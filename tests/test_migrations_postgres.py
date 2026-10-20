"""Opt-in PostgreSQL migration verification using disposable databases only."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _admin_url():
    if os.environ.get("RUN_POSTGRES_MIGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_MIGRATION_TESTS=1 to run disposable PostgreSQL migration tests")
    value = os.environ.get("TEST_ADMIN_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_ADMIN_DATABASE_URL or TEST_DATABASE_URL is required")
    url = make_url(value)
    return url.set(database=os.environ.get("TEST_ADMIN_DATABASE", "postgres"))


def _run_upgrade(database_url: str, revision: str = "head") -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(config, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _verify_disposable_database(target_revision: str):
    admin_url = _admin_url()
    database_name = f"ids_gaze_migration_{uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    target_url = admin_url.set(database=database_name)
    target_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        _run_upgrade(target_url.render_as_string(hide_password=False), target_revision)
        _run_upgrade(target_url.render_as_string(hide_password=False), "head")
        target_engine = create_engine(target_url)
        with target_engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == "20261020_0006"
    finally:
        if target_engine is not None:
            target_engine.dispose()
        admin_engine.dispose()
        cleanup_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with cleanup_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        finally:
            cleanup_engine.dispose()


def test_fresh_postgresql_database_reaches_current_head():
    _verify_disposable_database("base")


def test_existing_p3_revision_upgrades_to_current_head_without_reset():
    _verify_disposable_database("20261019_0003")
