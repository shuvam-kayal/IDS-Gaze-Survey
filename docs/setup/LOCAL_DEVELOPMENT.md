# Local development

Prerequisites: Docker Engine/Compose v2, Python 3.11+, Node.js 20+ and npm.

1. Copy `.env.example` to `.env` and keep values local.
2. Run `docker compose up --build`.
3. Check `http://localhost:8000/health` and `http://localhost:8000/docs`.
4. Stop with `docker compose down`; add `-v` only to intentionally delete local database data.

The API image installs only the runtime dependencies. Uvicorn's optional `standard` extras are intentionally not required for local API startup; the built-in reload mechanism is sufficient for this scaffold. Pip is configured with a longer network timeout and retries to reduce failures on slow package downloads. If a build still fails specifically while downloading packages, check connectivity to `pypi.org` and `files.pythonhosted.org`, then retry `docker compose build --no-cache api`.

Without Docker: create/activate a venv, run `pip install -e ".[dev]"`, `ruff check .`, `pytest`, then `npm install` and `npm run typecheck`.

The integration freeze selects PostgreSQL 16, SQLAlchemy 2.x, psycopg 3 and
Alembic for the persistence implementation. The current checkout still has no
migration runner or durable telemetry persistence; those are the next
coordinated implementation work. UI packages are typed domain scaffolds, not
full web apps. Do not use this setup for real participant data.
