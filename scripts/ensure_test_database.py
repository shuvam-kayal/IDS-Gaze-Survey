"""Create the dedicated local PostgreSQL test database if it is missing.

This helper never drops or resets a database.  It connects to the PostgreSQL
maintenance database using the same SQLAlchemy/psycopg stack as the project,
so host ``psql`` is not required.
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url


def _identifier(value: str) -> str:
    if not value or not value.replace("_", "").isalnum():
        raise ValueError("database name must contain only letters, numbers, and underscores")
    return value


def ensure_database(database_url: str, database_name: str) -> None:
    name = _identifier(database_name)
    target = make_url(database_url)
    admin_url: URL = target.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": name},
            ).scalar()
            if not exists:
                connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure the isolated IDS-Gaze test database exists")
    parser.add_argument("--database-url", required=True, help="development PostgreSQL URL")
    parser.add_argument("--database-name", default="attention_test")
    args = parser.parse_args()
    ensure_database(args.database_url, args.database_name)
    print(f"PostgreSQL database ensured: {args.database_name}")


if __name__ == "__main__":
    main()
