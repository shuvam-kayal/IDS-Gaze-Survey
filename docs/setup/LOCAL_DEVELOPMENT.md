# Local development

Prerequisites: Docker Engine/Compose v2, Python 3.11+, Node.js 20+ and npm.

1. On Windows, run `.\scripts\setup.ps1`; it creates the isolated `attention_test` database without dropping data.
2. Start with `.\scripts\start.ps1`.
3. Check `http://localhost:8000/health` and `http://localhost:8000/docs`.
4. Run PostgreSQL integration tests with `.\scripts\test-postgres.ps1`.
5. Stop with `docker compose down`; never use `-v` for routine development.

The setup script uses the existing Compose PostgreSQL service and the project's
declared SQLAlchemy/psycopg dependencies to create the test database; host
`psql` is not required. `DATABASE_URL` is the development database and
`TEST_DATABASE_URL` is always a separate explicit database. Integration test
fixtures intentionally skip when `TEST_DATABASE_URL` is absent.

On Linux/macOS, the equivalent core commands are:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
npm ci
docker compose up -d db
DATABASE_URL='postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5' python -m alembic upgrade head
python scripts/ensure_test_database.py --database-url 'postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5' --database-name attention_test
DATABASE_URL='postgresql+psycopg://attention:attention@localhost:5432/attention_test?connect_timeout=5' python -m alembic upgrade head
```

## Docker permissions

On Linux, `permission denied` while connecting to `/var/run/docker.sock` means
the current user cannot access the Docker daemon. For a one-time run, use
`sudo docker compose up --build`.

To use Docker without `sudo`, add your account to the `docker` group with
`sudo usermod -aG docker "$USER"`, then sign out and back in (or restart the
session). Verify access with `docker info` before rerunning
`docker compose up --build`. Membership in the `docker` group grants
root-equivalent privileges; only do this for a trusted account. Do not fix
this by making the Docker socket world-writable.

The API image installs only the runtime dependencies. Uvicorn's optional `standard` extras are intentionally not required for local API startup; the built-in reload mechanism is sufficient for this scaffold. Pip is configured with a longer network timeout and retries to reduce failures on slow package downloads. If a build still fails specifically while downloading packages, check connectivity to `pypi.org` and `files.pythonhosted.org`, then retry `docker compose build --no-cache api`.

Without Docker: create/activate a venv, run `pip install -e ".[dev]"`, `ruff check .`, `pytest`, then `npm install` and `npm run typecheck`.

The integration freeze selects PostgreSQL 16, SQLAlchemy 2.x, psycopg 3 and
Alembic. After PostgreSQL is running, apply all shared control-plane, telemetry,
geometry, and analytics migrations with `alembic upgrade head`; inspect
generated SQL without connecting with `alembic upgrade head --sql`. Start the
participant demo and researcher console separately with their workspace npm
scripts. The participant survey currently retains answers in page memory, and
analytics jobs run in-process. Do not use this setup for real participant data.
