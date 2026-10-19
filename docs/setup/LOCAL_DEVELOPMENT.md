# Local development

Prerequisites: Docker Engine/Compose v2, Python 3.11+, Node.js 20+ and npm.

1. Copy `.env.example` to `.env` and keep values local.
2. Run `docker compose up --build`.
3. Check `http://localhost:8000/health` and `http://localhost:8000/docs`.
4. Stop with `docker compose down`; add `-v` only to intentionally delete local database data.

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
Alembic. After PostgreSQL is running, apply the telemetry migration with
`alembic upgrade head`; inspect generated SQL without connecting with
`alembic upgrade head --sql`. The M2a slice provides durable event persistence,
idempotent ingestion and session lifecycle storage. UI packages are typed
domain scaffolds, not full web apps. Do not use this setup for real participant
data.
